# unimain.py
import os, time, asyncio, threading, sqlite3, traceback
import subprocess, gc, hashlib, base64
import socket
import time
import shutil
import builtins
import fnmatch
import mimetypes
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from activity.recent_sync import get_recent_syncs, record_sync
from index_controller.thumbnail_manager import read_thumbnail
from index_controller.ignore import should_ignore
from fastapi import Request
from rclone_service import *
from auth_manager import start_auth, auth_sessions

_orig_print = builtins.print

def print(*args, **kwargs):
    try:
        return _orig_print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [str(a).encode("ascii", "replace").decode("ascii") for a in args]
        return _orig_print(*safe_args, **kwargs)


# ── Paths & tunables ─────────────────────────────────────────
ROOT            = Path(__file__).parent.resolve()
ORGANIZED_ROOT  = Path("/mnt/storage/organized_files").resolve()
IMAGE_DIR       = Path("/mnt/storage/organized_files/images")

WIFI_INTERFACE = "wlan0"
HOTSPOT_NAME = "RadxaAP"
HOTSPOT_SSID = "RadxaSetup"
HOTSPOT_PASSWORD = "radxa1234"
HOTSPOT_IP = "10.99.0.1/24"

IMAGE_INDEX_DIR  = ROOT / "image_search_implementation_v2" / "storage"
IMAGE_INDEX_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_META_DB    = IMAGE_INDEX_DIR / "images_meta.db"
IMAGE_EMBED_DIR  = IMAGE_INDEX_DIR / "embeddings"
IMAGE_EMBED_DIR.mkdir(parents=True, exist_ok=True)
ANNOY_INDEX_PATH = IMAGE_INDEX_DIR / "annoy_index.ann"

ANNOY_DIM    = 512
ANNOY_N_TREES = 10
IMAGE_REBUILD_LOCK = threading.Lock()
IMAGE_EMBED_BATCH_REBUILD_THRESHOLD = 8
SEARCH_THREADPOOL = 2
SCAN_THREADPOOL   = 2

# llama-server — same build dir as llama-cli
LLAMA_SERVER_BIN  = ROOT / "llama.cpp" / "build" / "bin" / "llama-server"
LLAMA_MODEL       = ROOT / "llama.cpp" / "models" / "rocket-3B" / "rocket-3b.Q4_K_M.gguf"
LLAMA_SERVER_HOST = "127.0.0.1"
LLAMA_SERVER_PORT = 8765          # internal only, not exposed
LLAMA_SERVER_URL  = f"http://{LLAMA_SERVER_HOST}:{LLAMA_SERVER_PORT}"
LLAMA_CTX         = 1024
LLAMA_THREADS     = 4

# Queued requests wait up to this long before getting a 503
QUEUE_WAIT_TIMEOUT = 60   # seconds
THERMAL_LIMIT_C = 80  # °C — reject LLM calls above this

NETWORK_STATE = {
    "connected": False,
    "ssid": None,
    "hotspot_active": False
}
NETWORK_CONTROL_SUPPORTED = (
    os.name == "posix" and shutil.which("nmcli") is not None
)

# File access policy:
# - default allows arbitrary local file serving/listing for desktop/dev workflows
# - can be restricted by setting CONTEXTCORE_ALLOW_ARBITRARY_FILE_ACCESS=0 and
#   CONTEXTCORE_FILE_ROOTS to a ';'-separated allowlist.
ALLOW_ARBITRARY_FILE_ACCESS = (
    os.getenv("CONTEXTCORE_ALLOW_ARBITRARY_FILE_ACCESS", "1").strip().lower()
    not in {"0", "false", "no"}
)
FILE_ROOTS = [
    Path(p).expanduser().resolve()
    for p in os.getenv("CONTEXTCORE_FILE_ROOTS", "").split(";")
    if p.strip()
]

# NOTE: No idle-unload — whichever family is loaded stays loaded
#       until the OTHER family is explicitly requested.


# ═══════════════════════════════════════════════════════════════
#  ResourceManager
#  ─────────────────────────────────────────────────────────────
#  Rules:
#    • Only one model family (LLM or Embed) is in RAM at a time.
#    • On a family switch → the resident family is cleanly unloaded
#      BEFORE the new family starts loading.
#    • Concurrent requests for the SAME family: second request waits
#      on the asyncio.Lock and then runs immediately (no reload needed
#      because the same family is still active).
#    • Concurrent requests for DIFFERENT families: the latecomer waits
#      up to QUEUE_WAIT_TIMEOUT seconds; if still blocked → HTTP 503.
#    • No watchdog / idle timer — models stay loaded indefinitely.
# ═══════════════════════════════════════════════════════════════
class ResourceManager:
    STATE_IDLE  = "idle"
    STATE_LLM   = "llm"
    STATE_EMBED = "embed"

    def __init__(self):
        # Single lock — only one "activation" may proceed at a time.
        # Once activated, the lock is released so the same-family
        # requests can stack without re-triggering a model switch.
        self._switch_lock = asyncio.Lock()
        self._state       = self.STATE_IDLE

        self._llm_proc: Optional[subprocess.Popen] = None
        self._llm_ready  = False

    # ── context managers used by endpoint handlers ─────────────

    @asynccontextmanager
    async def llm_context(self):
        """
        Guarantee llama-server is running.
        If embed models are currently loaded, unload them first.
        Multiple concurrent LLM calls are fine — they share the
        already-running server with no extra switching overhead.
        """
        # Only lock during the *switch* phase; release before yielding
        # so parallel LLM calls don't serialise each other needlessly.
        if self._state != self.STATE_LLM:
            try:
                await asyncio.wait_for(
                    self._switch_lock.acquire(), timeout=QUEUE_WAIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    503, "Server busy — timed out waiting for LLM slot (60 s)"
                )
            try:
                # Double-check: another coroutine may have already switched
                if self._state != self.STATE_LLM:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._activate_llm
                    )
                    self._state = self.STATE_LLM
            finally:
                self._switch_lock.release()

        yield   # llama-server is up; caller does its work

    @asynccontextmanager
    async def embed_context(self):
        """
        Guarantee embed models can be lazily loaded.
        If llama-server is running, stop it first.
        Multiple concurrent embed calls are fine.
        """
        if self._state != self.STATE_EMBED:
            try:
                await asyncio.wait_for(
                    self._switch_lock.acquire(), timeout=QUEUE_WAIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    503, "Server busy — timed out waiting for embed slot (60 s)"
                )
            try:
                if self._state != self.STATE_EMBED:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._activate_embed
                    )
                    self._state = self.STATE_EMBED
            finally:
                self._switch_lock.release()

        yield   # embed models ready; caller does its work

    # ── internal activation (runs in thread executor) ──────────

    def _activate_llm(self):
        """Unload embed models → start llama-server."""
        print("🔄 ResourceManager → LLM mode")
        _unload_embed_models()
        self._start_llama_server()

    def _activate_embed(self):
        """Stop llama-server → embed models will load lazily on use."""
        print("🔄 ResourceManager → Embed mode")
        self._stop_llama_server()
        # CLIP / text engine intentionally NOT pre-loaded here;
        # they load on first actual use inside the request handler.

    # ── llama-server process management ────────────────────────

    def _start_llama_server(self):
        if self._llm_proc and self._llm_proc.poll() is None:
            print("   llama-server already running — reusing")
            return
        print("🚀 Starting llama-server …")
        cmd = [
            str(LLAMA_SERVER_BIN),
            "--model",     str(LLAMA_MODEL),
            "--host",      LLAMA_SERVER_HOST,
            "--port",      str(LLAMA_SERVER_PORT),
            "--ctx-size",  str(LLAMA_CTX),
            "--threads",   str(LLAMA_THREADS),
            "--n-predict", "256",
            "--no-mmap",   # avoids page-cache fights on 8 GB RAM
        ]
        self._llm_proc  = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._llm_ready = False
        print(f"   PID {self._llm_proc.pid} — waiting for /health …")
        self._wait_for_ready()

    def _wait_for_ready(self):
        """
        Poll llama-server /health with two windows:
          • 15 s fast-poll (0.5 s interval) — covers fast SSDs
          • 15 s slow-poll (1 s interval)   — covers slower eMMC / SD
        Raises RuntimeError if neither window succeeds.
        """
        for interval, window in [(0.5, 15), (1.0, 15)]:
            deadline = time.time() + window
            while time.time() < deadline:
                try:
                    r = requests.get(f"{LLAMA_SERVER_URL}/health", timeout=1)
                    if r.status_code == 200:
                        self._llm_ready = True
                        print("✅ llama-server ready")
                        return
                except requests.exceptions.ConnectionError:
                    pass
                time.sleep(interval)
        raise RuntimeError(
            "llama-server did not respond after 30 s — "
            "check LLAMA_SERVER_BIN and LLAMA_MODEL paths"
        )

    def _stop_llama_server(self):
        if not self._llm_proc:
            return
        pid = self._llm_proc.pid
        print(f"🛑 Stopping llama-server (PID {pid}) …")
        try:
            self._llm_proc.terminate()
            self._llm_proc.wait(timeout=8)
        except Exception:
            try:
                self._llm_proc.kill()
            except Exception:
                pass
        self._llm_proc  = None
        self._llm_ready = False
        gc.collect()
        print("   llama-server stopped")


# ── Embed model globals ───────────────────────────────────────
_clip_model       = None
_clip_processor   = None
_annoy_index      = None
_annoy_loaded     = False
_annoy_needs_rebuild = False
_text_engine      = None


def _unload_embed_models():
    global _clip_model, _clip_processor, _annoy_index, _annoy_loaded, _text_engine
    print("🧹 Unloading embed models …")
    if _annoy_index and hasattr(_annoy_index, "unload"):
        try:
            _annoy_index.unload()
        except Exception:
            pass
    _annoy_index    = None
    _annoy_loaded   = False
    _clip_model     = None
    _clip_processor = None
    _text_engine    = None
    gc.collect()
    print("   Done")


def get_text_engine():
    global _text_engine
    if _text_engine is None:
        mod = __import__(
            "text_search_implementation_v2.search", fromlist=["TextSearchEngineV2"]
        )
        _text_engine = mod.TextSearchEngineV2()
    return _text_engine


def lazy_load_clip():
    global _clip_model, _clip_processor
    if _clip_model is None:
        from transformers import CLIPProcessor, CLIPModel
        import torch
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model     = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model.to(torch.device("cpu")).eval()
    return _clip_model, _clip_processor


def embed_text_with_clip(text: str):
    model, processor = lazy_load_clip()
    import torch
    inputs = {k: v.to("cpu") for k, v in
              processor(text=[text], return_tensors="pt", padding=True).items()}
    with torch.no_grad():
        feats = model.get_text_features(**inputs)
        # Some transformer/CLIP variants may return model output objects.
        if not isinstance(feats, torch.Tensor):
            if hasattr(feats, "text_embeds") and feats.text_embeds is not None:
                feats = feats.text_embeds
            elif hasattr(feats, "pooler_output") and feats.pooler_output is not None:
                feats = feats.pooler_output
            elif hasattr(feats, "last_hidden_state") and feats.last_hidden_state is not None:
                feats = feats.last_hidden_state[:, 0, :]
            else:
                raise RuntimeError("Unsupported CLIP text feature output type")
    return (feats / feats.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy().astype("float32")


def embed_image_file(image_path: Path):
    model, processor = lazy_load_clip()
    from PIL import Image
    import torch
    img = Image.open(image_path).convert("RGB")
    inputs = {k: v.to("cpu") for k, v in processor(images=img, return_tensors="pt").items()}
    with torch.no_grad():
        feats = model.get_image_features(**inputs)
        if not isinstance(feats, torch.Tensor):
            if hasattr(feats, "image_embeds") and feats.image_embeds is not None:
                feats = feats.image_embeds
            elif hasattr(feats, "pooler_output") and feats.pooler_output is not None:
                feats = feats.pooler_output
            elif hasattr(feats, "last_hidden_state") and feats.last_hidden_state is not None:
                feats = feats.last_hidden_state[:, 0, :]
            else:
                raise RuntimeError("Unsupported CLIP image feature output type")
    return (feats / feats.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy().astype("float32")


def get_video_module():
    return __import__(
        "video_search_implementation_v2.video_index",
        fromlist=["scan_video_index", "search_videos"]
    )


# ── Annoy helpers ─────────────────────────────────────────────
def ensure_annoy_loaded():
    global _annoy_index, _annoy_loaded
    if _annoy_loaded:
        return True
    try:
        from annoy import AnnoyIndex
        if not ANNOY_INDEX_PATH.exists():
            _annoy_index = AnnoyIndex(ANNOY_DIM, "angular")
        else:
            ai = AnnoyIndex(ANNOY_DIM, "angular")
            ai.load(str(ANNOY_INDEX_PATH))
            _annoy_index = ai
        _annoy_loaded = True
        return True
    except Exception as e:
        print("Annoy load failed:", e)
        return False


def rebuild_annoy_index(iter_fn):
    global _annoy_index, _annoy_loaded, _annoy_needs_rebuild
    from annoy import AnnoyIndex
    with IMAGE_REBUILD_LOCK:
        print("🔧 Rebuilding Annoy index …")
        ai = AnnoyIndex(ANNOY_DIM, "angular")
        i  = 0
        for _id, vec in iter_fn():
            ai.add_item(_id, vec)
            i += 1
        if i == 0:
            _annoy_index = AnnoyIndex(ANNOY_DIM, "angular")
        else:
            ai.build(ANNOY_N_TREES)
            ai.save(str(ANNOY_INDEX_PATH))
            _annoy_index = ai
        _annoy_loaded        = True
        _annoy_needs_rebuild = False
        print(f"🔧 Annoy rebuilt: {i} items")


def all_vectors_iterator():
    for path, info in get_known_images().items():
        aid = info.get("annoy_id")
        if not aid:
            continue
        try:
            import numpy as np
            yield int(aid), np.load(str(IMAGE_EMBED_DIR / f"{aid}.npy"))
        except Exception:
            continue


# ── Image metadata DB ─────────────────────────────────────────
def _get_image_conn():
    conn = sqlite3.connect(str(IMAGE_META_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_image_meta_db():
    conn = _get_image_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS images (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        path     TEXT UNIQUE,
        mtime    REAL,
        annoy_id INTEGER
    )""")
    conn.commit()
    conn.close()


def get_known_images():
    conn = _get_image_conn()
    rows = conn.execute("SELECT id, path, mtime, annoy_id FROM images").fetchall()
    conn.close()
    return {r["path"]: {"id": r["id"], "mtime": r["mtime"], "annoy_id": r["annoy_id"]}
            for r in rows}


def add_or_update_image(path: str, mtime: float, annoy_id: Optional[int]):
    conn = _get_image_conn()
    conn.execute("""INSERT INTO images (path, mtime, annoy_id) VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE
        SET mtime=excluded.mtime, annoy_id=excluded.annoy_id""",
        (path, mtime, annoy_id))
    conn.commit()
    conn.close()


def get_next_annoy_id():
    conn = _get_image_conn()
    row  = conn.execute("SELECT MAX(annoy_id) as mx FROM images").fetchone()
    conn.close()
    return int(row[0] or 0) + 1


# ── Scan helpers ──────────────────────────────────────────────
def scan_text_index():
    try:
        mod = __import__(
            "text_search_implementation_v2.index_worker", fromlist=["run_scan"]
        )
        if hasattr(mod, "run_scan"):
            mod.run_scan()
            return {"status": "ok", "updated": True}
        if hasattr(mod, "main"):
            mod.main()
            return {"status": "ok", "updated": True}
        return {"status": "ok", "updated": False}
    except ModuleNotFoundError:
        return {"status": "ok", "updated": False}
    except Exception:
        traceback.print_exc()
        return {"status": "error"}


def scan_image_index():
    init_image_meta_db()
    known     = get_known_images()
    new_count = 0
    next_aid  = get_next_annoy_id()
    exts      = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

    for p in IMAGE_DIR.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        s    = str(p)
        info = known.get(s)
        if info and abs(info["mtime"] - mtime) < 0.001:
            continue
        try:
            vec = embed_image_file(p)
        except Exception as e:
            print("⚠️ embed failed:", e)
            continue
        try:
            import numpy as np
            np.save(str(IMAGE_EMBED_DIR / f"{next_aid}.npy"), vec)
        except Exception as e:
            print("⚠️ save failed:", e)
            continue
        add_or_update_image(s, mtime, next_aid)
        next_aid  += 1
        new_count += 1

    if new_count > 0:
        global _annoy_needs_rebuild
        _annoy_needs_rebuild = True
        threading.Thread(
            target=lambda: rebuild_annoy_index(all_vectors_iterator), daemon=True
        ).start()

    return {"status": "ok", "new_vectors": new_count}


def scan_video_index_wrapper():
    try:
        return get_video_module().scan_video_index(
            Path("/mnt/storage/organized_files/video")
        )
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


def scan_audio_index_wrapper():
    try:
        import sys
        subprocess.Popen([sys.executable, "-m", "audio_search_implementation_v2.worker"])
        return {"status": "accepted"}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


# ── Search helpers ────────────────────────────────────────────
def run_text_search(
    query: str,
    top_k: int = 20,
    include_metadata: bool = False,
    chunk_chars: int = 900,
    chunk_overlap: int = 120,
    exclude_sources: set[str] | None = None,
):
    try:
        return get_text_engine().search(
            query=query,
            categories=None,
            top_k=top_k,
            include_metadata=include_metadata,
            chunk_chars=chunk_chars,
            chunk_overlap=chunk_overlap,
            exclude_sources=exclude_sources,
        )
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def run_image_search(query: str, top_k: int = 10):
    try:
        init_image_meta_db()
        if not ensure_annoy_loaded():
            return {"error": "annoy_unavailable"}
        conn = _get_image_conn()
        cnt  = conn.execute(
            "SELECT COUNT(*) as c FROM images WHERE annoy_id IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        if cnt > 0 and (not ANNOY_INDEX_PATH.exists() or _annoy_needs_rebuild):
            rebuild_annoy_index(all_vectors_iterator)
        qvec = embed_text_with_clip(query)
        if _annoy_index is None:
            return {"error": "annoy_not_loaded"}
        ids, dists = _annoy_index.get_nns_by_vector(
            qvec.tolist(), top_k, include_distances=True
        )
        conn    = _get_image_conn()
        results = []
        for aid, dist in zip(ids, dists):
            row = conn.execute(
                "SELECT path FROM images WHERE annoy_id=?", (aid,)
            ).fetchone()
            if row:
                results.append({
                    "path":     row[0],
                    "annoy_id": aid,
                    "score":    float(1.0 - dist / 2.0),
                })
        conn.close()
        return {"hits": results[:2]}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def run_video_search(query: str, top_k: int = 10):
    try:
        return get_video_module().search_videos(query, top_k)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  FastAPI app
# ═══════════════════════════════════════════════════════════════
app = FastAPI(title="Unified Search — memory-managed")
rm  = ResourceManager()


@app.on_event("startup")
async def startup():
    init_image_meta_db()
    # No watchdog started — models persist until displaced by opposite family
    print("🚀 unimain started (no idle-unload — models persist until switched)")
    network_bootstrap()
    auto_prewarm = os.getenv("CONTEXTCORE_PREWARM_ON_STARTUP", "1").strip().lower() not in {"0", "false", "no"}
    if auto_prewarm:
        print("🔥 startup prewarm enabled (text + CLIP)")
        try:
            get_text_engine()
        except Exception as e:
            print("⚠️ text prewarm failed:", e)
        try:
            lazy_load_clip()
            print("✅ CLIP prewarmed")
        except Exception as e:
            print("⚠️ CLIP prewarm failed:", e)


@app.on_event("shutdown")
async def shutdown():
    rm._stop_llama_server()
    _unload_embed_models()


# ── Health ────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":         "ok",
        "resource_state": rm._state,
        "llm_running":    rm._llm_proc is not None and rm._llm_proc.poll() is None,
    }


# ── /llm ─────────────────────────────────────────────────────
@app.post("/llm")
async def run_llm(
    query:       str   = Body(..., embed=True),
    max_tokens:  int   = Body(256, embed=True),
    temperature: float = Body(0.7, embed=True),
):
    """
    LLM inference via llama-server.

    On first call (or after a switch from embed mode):
      embed models unloaded → llama-server spawned → weights loaded once.
    On subsequent calls while in LLM mode:
      llama-server already running → just proxy the request, no reload.
    Any concurrent /search call that arrives while this is running:
      queued → waits up to 60 s → then served (llama-server is stopped first).
    """
    if not query.strip():
        raise HTTPException(400, "Empty query")
    
    current_temp = get_cpu_temp_c()
    if current_temp >= THERMAL_LIMIT_C:
        raise HTTPException(
            status_code=503,
            detail={
                "error":           "thermal_throttle",
                "message":         f"CPU too hot ({current_temp:.1f}°C / limit {THERMAL_LIMIT_C}°C). Please try again shortly.",
                "current_temp_c":  current_temp,
                "limit_temp_c":    THERMAL_LIMIT_C,
            },
            headers={"Retry-After": "30"},
        )
        
    async with rm.llm_context():
        payload = {
            "prompt":      query,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["</s>", "<|im_end|>"],
            "stream":      False,
        }
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(
                    f"{LLAMA_SERVER_URL}/completion",
                    json=payload,
                    timeout=120,
                ),
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "response":         data.get("content", ""),
                "tokens_predicted": data.get("tokens_predicted"),
                "stop_reason":      data.get("stop_type"),
            }
        except requests.exceptions.Timeout:
            raise HTTPException(504, "LLM inference timed out")
        except Exception as e:
            raise HTTPException(500, str(e))


# ── /search ───────────────────────────────────────────────────
@app.get("/search")
async def unified_search(
    query: str = Query(..., min_length=1),
    top_k: int = Query(20, ge=1, le=200),
    modality: str = Query("all"),
    text_include_metadata: bool = Query(False),
    text_chunk_chars: int = Query(900, ge=200, le=4000),
    text_chunk_overlap: int = Query(120, ge=0, le=1000),
    exclude_sources: str | None = Query(None),
):
    """
    Unified text + image + video search.

    On first call (or after LLM mode): llama-server stopped → embed models
    load lazily. On subsequent calls while in embed mode: models already
    warm, no reload overhead.
    """
    q = query.strip()
    if not q:
        raise HTTPException(400, "empty query")

    mode = modality.strip().lower()
    if mode not in {"all", "text", "image", "video", "audio"}:
        raise HTTPException(400, "invalid modality; expected all,text,image,video,audio")

    excluded: set[str] = set()
    if exclude_sources:
        excluded = {p.strip() for p in exclude_sources.split(",") if p.strip()}

    async with rm.embed_context():
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=SEARCH_THREADPOOL) as ex:
            text_res = image_res = video_res = None
            if mode in {"all", "text", "audio"}:
                try:
                    text_res  = await asyncio.wait_for(
                        loop.run_in_executor(
                            ex,
                            run_text_search,
                            q,
                            top_k,
                            text_include_metadata,
                            text_chunk_chars,
                            text_chunk_overlap,
                            excluded,
                        ),
                        timeout=8,
                    )
                except Exception as e:
                    text_res  = {"error": str(e)}
            if mode in {"all", "image"}:
                try:
                    image_res = await asyncio.wait_for(
                        loop.run_in_executor(ex, run_image_search, q, min(50, top_k)), timeout=10)
                except Exception as e:
                    image_res = {"error": str(e)}
            if mode in {"all", "video"}:
                try:
                    video_res = await asyncio.wait_for(
                        loop.run_in_executor(ex, run_video_search, q, min(50, top_k)), timeout=12)
                except Exception as e:
                    video_res = {"error": str(e)}

    out = {"query": q, "modality": mode}
    out["text"]  = ({"count": len(text_res),  "results": text_res}
                    if isinstance(text_res, list)
                    else {"count": 0, "results": [],
                          "error": text_res.get("error") if isinstance(text_res, dict) else None})
    out["image"] = ({"count": len(image_res["hits"]), "results": image_res["hits"]}
                    if isinstance(image_res, dict) and "hits" in image_res
                    else {"count": 0, "results": [],
                          "error": image_res.get("error") if isinstance(image_res, dict) else None})
    out["video"] = ({"count": len(video_res["hits"]), "results": video_res["hits"]}
                    if isinstance(video_res, dict) and "hits" in video_res
                    else {"count": 0, "results": [],
                          "error": video_res.get("error") if isinstance(video_res, dict) else None})
    return out


@app.get("/search/text/neighbors")
def text_neighbors(
    chunk_id: str = Query(..., min_length=8),
    direction: str = Query("next"),
    count: int = Query(1, ge=1, le=5),
):
    try:
        result = get_text_engine().get_neighbors(
            chunk_id=chunk_id,
            direction=direction,
            count=count,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


# ── /index/scan ───────────────────────────────────────────────
@app.post("/index/scan")
async def index_scan(
    run_text:  bool = True,
    run_image: bool = True,
    run_video: bool = True,
    run_audio: bool = True,
):
    """Fire-and-forget scan. Acquires embed context so it queues
    correctly behind any active LLM call."""

    async def _do_scans():
        async with rm.embed_context():
            loop = asyncio.get_event_loop()
            pool = ThreadPoolExecutor(max_workers=SCAN_THREADPOOL)
            jobs = []
            if run_text:  jobs.append(("text",  loop.run_in_executor(pool, scan_text_index)))
            if run_image: jobs.append(("image", loop.run_in_executor(pool, scan_image_index)))
            if run_video: jobs.append(("video", loop.run_in_executor(pool, scan_video_index_wrapper)))
            if run_audio: jobs.append(("audio", loop.run_in_executor(pool, scan_audio_index_wrapper)))
            for name, fut in jobs:
                try:
                    print(f"scan [{name}]:", await fut)
                except Exception as e:
                    print(f"scan [{name}] error:", e)

    asyncio.ensure_future(_do_scans())
    submitted = [n for n, f in [
        ("text", run_text), ("image", run_image),
        ("video", run_video), ("audio", run_audio)
    ] if f]
    return {"status": "accepted", "jobs": submitted}


# ── /image/index/status ───────────────────────────────────────
@app.get("/image/index/status")
def image_index_status():
    init_image_meta_db()
    conn = _get_image_conn()
    cnt  = conn.execute(
        "SELECT COUNT(*) as c FROM images WHERE annoy_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    return {
        "annoy_exists":        ANNOY_INDEX_PATH.exists(),
        "indexed_images":      int(cnt),
        "annoy_needs_rebuild": bool(_annoy_needs_rebuild),
    }


# ── Admin ─────────────────────────────────────────────────────
@app.post("/admin/prewarm/llm")
async def prewarm_llm():
    """Load llama-server now so the first real /llm call is instant."""
    async with rm.llm_context():
        return {
            "status": "ok",
            "note":   "llama-server warm and resident",
            "pid":    rm._llm_proc.pid if rm._llm_proc else None,
        }


@app.post("/admin/prewarm/clip")
async def prewarm_clip():
    """Pre-load CLIP so the first /search call doesn't pay load time."""
    async with rm.embed_context():
        try:
            lazy_load_clip()
            return {"status": "ok", "note": "CLIP loaded"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@app.post("/admin/force-switch/llm")
async def force_switch_llm():
    """Force immediate switch to LLM mode (stops embed models)."""
    if rm._switch_lock.locked():
        return {"status": "busy", "note": "switch already in progress"}
    async with rm.llm_context():
        return {"status": "ok", "resource_state": rm._state,
                "pid": rm._llm_proc.pid if rm._llm_proc else None}


@app.post("/admin/force-switch/embed")
async def force_switch_embed():
    """Force immediate switch to Embed mode (stops llama-server)."""
    if rm._switch_lock.locked():
        return {"status": "busy", "note": "switch already in progress"}
    async with rm.embed_context():
        return {"status": "ok", "resource_state": rm._state}


# ── File serving ──────────────────────────────────────────────
@app.get("/files")
def get_file(path: str = Query(...)):
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "File not found")
    if not _is_path_allowed(p):
        raise HTTPException(403, "Path not allowed")
    return FileResponse(
        path=p, filename=p.name, media_type=None,
        headers={"Content-Disposition": f'inline; filename="{p.name}"'},
    )


@app.get("/files/list")
def list_files(
    directory: str = Query(...),
    recursive: bool = Query(True),
    limit: int = Query(200, ge=1, le=2000),
    pattern: str = Query("*"),
):
    root = Path(directory).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(404, "Directory not found")
    if not _is_path_allowed(root):
        raise HTTPException(403, "Path not allowed")

    walker = root.rglob("*") if recursive else root.glob("*")
    out = []
    for p in walker:
        if not p.is_file():
            continue
        if pattern and not fnmatch.fnmatch(p.name, pattern):
            continue
        if should_ignore(p):
            continue
        mime, _ = mimetypes.guess_type(str(p))
        out.append(
            {
                "path": str(p),
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
                "mime_type": mime or "application/octet-stream",
            }
        )
        if len(out) >= limit:
            break
    return {"directory": str(root), "count": len(out), "files": out}


@app.post("/files/preflight")
def preflight_file_add(
    relative_dir: str = Body(..., embed=True),
    filename:     str = Body(..., embed=True),
    sha256:       str = Body(..., embed=True),
):
    target_dir = (ORGANIZED_ROOT / relative_dir).resolve()
    if ORGANIZED_ROOT not in target_dir.parents and target_dir != ORGANIZED_ROOT:
        raise HTTPException(403, "Invalid directory")
    target = target_dir / filename
    if not target.exists():
        return {"action": "accept", "filename": filename}
    if sha256_file(target) == sha256:
        return {"action": "reject", "reason": "Exact duplicate already exists"}
    i = 1
    while True:
        c = target_dir / f"{target.stem}[{i}]{target.suffix}"
        if not c.exists():
            return {"action": "rename", "filename": c.name}
        i += 1


@app.get("/activity/recent")
def recent_activity():
    return {"items": get_recent_syncs()}


@app.post("/thumbnails/fetch")
def fetch_thumbnails(
    category: str       = Body(...),
    paths:    list[str] = Body(...),
):
    results = []
    for p in paths:
        src = Path(p)
        if not src.exists() or should_ignore(src):
            continue
        data = read_thumbnail(src, category)
        if data:
            results.append({
                "path":      p,
                "thumbnail": base64.b64encode(data).decode(),
                "mime":      "image/jpeg",
            })
    return {"count": len(results), "thumbnails": results}


@app.get("/storage/usage")
def storage_usage():
    if not os.path.exists("/mnt/storage"):
        raise HTTPException(404, "Storage not found")
    s     = os.statvfs("/mnt/storage")
    total = s.f_frsize * s.f_blocks
    free  = s.f_frsize * s.f_bavail
    used  = total - free
    return {
        "path":         "/mnt/storage",
        "total_bytes":  total,
        "used_bytes":   used,
        "free_bytes":   free,
        "used_percent": round(used / total * 100, 2) if total else 0.0,
    }

# middleware protection definition 

@app.middleware("http")
async def network_guard(request: Request, call_next):
    path = request.url.path

    # Always allow health + network endpoints
    allowed_paths = [
        "/health",
        "/network/status",
        "/wifi/scan",
        "/wifi/connect","/configure-wifi"
    ]

    if path in allowed_paths:
        return await call_next(request)

    # If not connected and not hotspot active → block
    if not NETWORK_STATE["connected"] and not NETWORK_STATE["hotspot_active"]:
        return JSONResponse(
            status_code=503,
            content={"error": "Network not ready"}
        )

    return await call_next(request)

# network status endpoint
@app.get("/network/status")
def network_status():
    return {
        "connected": NETWORK_STATE["connected"],
        "ssid": NETWORK_STATE["ssid"],
        "hotspot_active": NETWORK_STATE["hotspot_active"],
        "hotspot_name": HOTSPOT_NAME if NETWORK_STATE["hotspot_active"] else None
    }

@app.post("/configure-wifi")
def configure_wifi(data: dict):
    if not NETWORK_CONTROL_SUPPORTED:
        raise HTTPException(501, "WiFi configuration via nmcli is not supported on this host")

    ssid = data.get("ssid")
    password = data.get("password")

    if not ssid or not password:
        raise HTTPException(400, "Missing SSID or password")

    try:
        # 1️⃣ Stop hotspot FIRST
        subprocess.run(["nmcli", "connection", "down", HOTSPOT_NAME], check=False)
        subprocess.run(["nmcli", "connection", "delete", HOTSPOT_NAME], check=False)

        time.sleep(2)  # give interface time to reset

        # 2️⃣ Rescan WiFi
        subprocess.run(["nmcli", "device", "wifi", "rescan"], check=False)

        # 3️⃣ Connect
        subprocess.run(
            ["nmcli", "device", "wifi", "connect", ssid, "password", password],
            check=True
        )

        return {"status": "connected"}

    except subprocess.CalledProcessError:
        raise HTTPException(500, "Failed to connect to WiFi")

@app.post("/storage/init")
def init_storage(storage_type: str):
    session_id = start_auth(storage_type)
    return {"session_id": session_id}


@app.get("/storage/poll")
def poll_storage(session_id: str):

    session = auth_sessions.get(session_id)

    if not session:
        return {"error": "invalid_session"}

    return {
        "status": session["status"],
        "verification_url": session["verification_url"],
        "user_code": session["user_code"]
    }

@app.get("/storage/status")
def storage_status(remote_name: str):
    return {"connected": check_remote(remote_name)}


@app.post("/sync/start")
def sync_start(remote_name: str):
    local_path = f"/opt/yourapp/data/{remote_name}"
    return start_copy(remote_name, local_path)


@app.get("/sync/status")
def sync_status(job_id: int):
    return get_job_status(job_id)

@app.post("/storage/finalize")
def finalize_storage(session_id: str, remote_name: str):

    session = auth_sessions.get(session_id)

    if not session or session["status"] != "completed":
        return {"error": "not_ready"}

    token_json = session["token"]

    # Create remote
    requests.post(
        f"{RCLONE_URL}/config/create",
        json={
            "name": remote_name,
            "type": "drive"
        }
    )

    # Inject token
    requests.post(
        f"{RCLONE_URL}/config/update",
        json={
            "name": remote_name,
            "parameters": {
                "token": token_json
            }
        }
    )

    return {"success": True}

# ── Utility ───────────────────────────────────────────────────
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_path_allowed(p: Path) -> bool:
    if ALLOW_ARBITRARY_FILE_ACCESS:
        return True
    rp = p.resolve()
    for base in FILE_ROOTS:
        if rp == base or base in rp.parents:
            return True
    return False


def get_cpu_temp_c() -> float:
    """Return highest temperature across all thermal zones in °C."""
    highest = 0.0
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            val = float(zone.read_text().strip()) / 1000.0
            if val > highest:
                highest = val
        except Exception:
            continue
    return highest

def get_current_wifi():
    try:
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            text=True
        )
        for line in result.strip().split("\n"):
            if line.startswith("yes:"):
                ssid = line.split(":")[1]
                return ssid
        return None
    except Exception:
        return None

def start_hotspot():
    print("🔥 Starting hotspot mode...")
    subprocess.run([
        "nmcli", "device", "wifi", "hotspot",
        "ssid", HOTSPOT_NAME,
        "password", HOTSPOT_PASSWORD
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    NETWORK_STATE["hotspot_active"] = True
    NETWORK_STATE["connected"] = False
    NETWORK_STATE["ssid"] = None
    NETWORK_STATE["hotspot_active"] = True


def stop_hotspot():
    subprocess.run(["nmcli", "connection", "down", HOTSPOT_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    NETWORK_STATE["hotspot_active"] = False

def initialize_network():
    print("🔍 Checking network state on startup...")

    ssid = get_current_wifi()

    if ssid:
        print(f"✅ Connected to WiFi: {ssid}")
        NETWORK_STATE["connected"] = True
        NETWORK_STATE["ssid"] = ssid
        NETWORK_STATE["hotspot_active"] = False
    else:
        print("❌ Not connected to WiFi.")
        NETWORK_STATE["connected"] = False
        NETWORK_STATE["ssid"] = None
        start_hotspot()

def is_connected():
    try:
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "GENERAL.STATE", "device","show", WIFI_INTERFACE],
            text=True
        ).strip()
        if result.startswith("GENERAL.STATE:100"):
            return True
        return False

    except Exception as e:
        print("Network check failed:", e)
        return False

def stop_system_dnsmasq():
    if shutil.which("systemctl") is None:
        return
    subprocess.run(["sudo", "systemctl", "stop", "dnsmasq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_hotspot():
    print("⚡ Starting Radxa Hotspot...")

    subprocess.run(["nmcli", "connection", "delete", HOTSPOT_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    subprocess.run([
        "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", WIFI_INTERFACE,
        "mode", "ap",
        "con-name", HOTSPOT_NAME,
        "ssid", HOTSPOT_SSID
    ])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "802-11-wireless.band", "bg"])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "802-11-wireless-security.key-mgmt", "wpa-psk"])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "802-11-wireless-security.psk", HOTSPOT_PASSWORD])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "ipv4.method", "shared"])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "ipv4.addresses", HOTSPOT_IP])

    subprocess.run(["nmcli", "connection", "modify", HOTSPOT_NAME,
                    "ipv6.method", "ignore"])

    subprocess.run(["nmcli", "connection", "up", HOTSPOT_NAME])

    time.sleep(3)

    print("✅ Hotspot active at 10.99.0.1")

def network_bootstrap():
    print("checking network state on startup...")
    if not NETWORK_CONTROL_SUPPORTED:
        print("nmcli not available; skipping hotspot bootstrap")
        NETWORK_STATE["connected"] = True
        NETWORK_STATE["ssid"] = "local-dev"
        NETWORK_STATE["hotspot_active"] = False
        return

    if is_connected():
        ssid = get_current_wifi()
        print(f"connected to wifi: {ssid}")
        NETWORK_STATE["connected"] = True
        NETWORK_STATE["ssid"] = ssid
        NETWORK_STATE["hotspot_active"] = False

    else:
        print("❌ Not connected. Enabling hotspot...")

        NETWORK_STATE["connected"] = False
        NETWORK_STATE["ssid"] = None
        
        stop_system_dnsmasq()
        start_hotspot()

        NETWORK_STATE["hotspot_active"] = True

