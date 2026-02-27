# video_search_implementation_v2/video_index.py
import os
import sqlite3
import threading
import subprocess
import tempfile
import math
from pathlib import Path
from typing import Callable, Iterator, Tuple, Optional

ROOT = Path(__file__).parent.resolve()
STORAGE_DIR = ROOT / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_META_DB = STORAGE_DIR / "videos_meta.db"
VIDEO_EMBED_DIR = STORAGE_DIR / "embeddings"
VIDEO_EMBED_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_ANNOY_INDEX = STORAGE_DIR / "video_annoy_index.ann"
ANNOY_DIM = 512
ANNOY_N_TREES = 10

VIDEO_REBUILD_LOCK = threading.Lock()

# Lazy annoy instance for video index (separate from images)
_video_annoy = None
_video_annoy_loaded = False
_video_annoy_needs_rebuild = False

# CLIP embedding helpers are imported from your unimain or shared module.
# Expected: embed_image_file(path) and embed_text_with_clip(text) are available.
# If not, copy lazy_load_clip/embed_image_file/embed_text_with_clip functions here.

def _get_conn():
    conn = sqlite3.connect(str(VIDEO_META_DB))
    conn.row_factory = sqlite3.Row
    return conn

def init_video_db():
    conn = _get_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE,
        mtime REAL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS frames (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER,
        timestamp REAL,
        annoy_id INTEGER UNIQUE
    )
    """)
    conn.commit()
    conn.close()

def get_known_videos():
    conn = _get_conn()
    cur = conn.execute("SELECT id, path, mtime FROM videos")
    rows = cur.fetchall()
    conn.close()
    return {r["path"]: {"id": r["id"], "mtime": r["mtime"]} for r in rows}

def add_or_update_video(path: str, mtime: float):
    conn = _get_conn()
    conn.execute("INSERT INTO videos (path, mtime) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime", (path, mtime))
    conn.commit()
    conn.close()

def add_frame(video_id: int, timestamp: float, annoy_id: int):
    conn = _get_conn()
    conn.execute("INSERT INTO frames (video_id, timestamp, annoy_id) VALUES (?, ?, ?)", (video_id, timestamp, annoy_id))
    conn.commit()
    conn.close()

def get_next_annoy_id():
    conn = _get_conn()
    cur = conn.execute("SELECT MAX(annoy_id) as mx FROM frames")
    row = cur.fetchone()
    conn.close()
    mx = row[0] if row and row[0] is not None else 0
    return int(mx) + 1

def all_video_vectors_iterator() -> Iterator[Tuple[int, "np.ndarray"]]:
    """Yield (annoy_id, vector) for frames that have an annoy_id mapping."""
    known = {}
    conn = _get_conn()
    cur = conn.execute("SELECT annoy_id FROM frames WHERE annoy_id IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    import numpy as np
    for r in rows:
        aid = r["annoy_id"]
        emb_path = VIDEO_EMBED_DIR / f"{aid}.npy"
        if not emb_path.exists():
            continue
        try:
            v = np.load(str(emb_path))
            yield int(aid), v
        except Exception:
            continue

# --- Annoy management for video index ---
def ensure_video_annoy_loaded():
    global _video_annoy, _video_annoy_loaded
    if _video_annoy_loaded:
        return True
    try:
        from annoy import AnnoyIndex
    except Exception as e:
        print("Annoy import failed for video:", e)
        return False
    ai = AnnoyIndex(ANNOY_DIM, "angular")
    if not VIDEO_ANNOY_INDEX.exists():
        _video_annoy = ai
        _video_annoy_loaded = True
        return True
    ai.load(str(VIDEO_ANNOY_INDEX))
    _video_annoy = ai
    _video_annoy_loaded = True
    return True

def unload_video_annoy():
    global _video_annoy, _video_annoy_loaded
    try:
        if _video_annoy is not None and hasattr(_video_annoy, "unload"):
            _video_annoy.unload()
    except Exception:
        pass
    _video_annoy = None
    _video_annoy_loaded = False

def rebuild_video_annoy_index(all_vectors_iter: Callable[[], Iterator[Tuple[int, "np.ndarray"]]]):
    from annoy import AnnoyIndex
    global _video_annoy, _video_annoy_loaded, _video_annoy_needs_rebuild
    with VIDEO_REBUILD_LOCK:
        print("🔧 Rebuilding video Annoy index from disk vectors...")
        ai = AnnoyIndex(ANNOY_DIM, "angular")
        i = 0
        for aid, vec in all_vectors_iter():
            ai.add_item(aid, vec)
            i += 1
        if i == 0:
            try:
                if VIDEO_ANNOY_INDEX.exists():
                    VIDEO_ANNOY_INDEX.unlink()
            except:
                pass
            _video_annoy = AnnoyIndex(ANNOY_DIM, "angular")
            _video_annoy_loaded = True
            _video_annoy_needs_rebuild = False
            print("🔧 Video Annoy rebuilt: 0 items")
            return
        ai.build(ANNOY_N_TREES)
        ai.save(str(VIDEO_ANNOY_INDEX))
        _video_annoy = ai
        _video_annoy_loaded = True
        _video_annoy_needs_rebuild = False
        print(f"🔧 Video Annoy rebuilt: {i} items")

# --- Frame extraction helpers ---
def extract_frames_scene_or_sample(video_path: str, max_frames: int = 80, scene_thresh: float = 0.4):
    """
    Extract frames using scene detection. If too few frames are detected, fallback to time sampling.
    Returns list of tuples (temp_image_path, timestamp_seconds)
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="video_frames_"))
    frames = []
    # scene detection extraction
    # we use ffmpeg select filter to output frames when scene change occurs
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-vf", f"select='gt(scene,{scene_thresh})',scale=640:-1",
        "-vsync", "vfr",
        str(tmpdir / "frame_%06d.jpg")
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # collect files
        files = sorted(tmpdir.glob("frame_*.jpg"))
        for f in files:
            frames.append((str(f), None))
    except subprocess.CalledProcessError:
        # scene detection might fail; fallback to sampling
        pass

    if len(frames) == 0:
        # fallback sampling every N seconds
        # get duration
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            dur = float(probe.stdout.decode().strip())
        except Exception:
            dur = 60.0
        step = max(1.0, dur / max_frames)
        # use ffmpeg to extract frames at timestamps
        timestamps = [i*step for i in range(int(min(max_frames, math.ceil(dur/step))))]
        # extract frames one by one (avoids storing too many)
        for idx, ts in enumerate(timestamps):
            outp = tmpdir / f"sample_{idx:06d}.jpg"
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(ts),
                "-i", video_path,
                "-frames:v", "1",
                "-vf", "scale=640:-1",
                str(outp)
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                frames.append((str(outp), float(ts)))
            except subprocess.CalledProcessError:
                continue

    # cap frames
    if len(frames) > max_frames:
        frames = frames[:max_frames]
    return tmpdir, frames  # caller should cleanup tmpdir when done

# --- Dedup helper ---
def cosine_sim(a, b):
    import numpy as np
    a = a.astype("float32")
    b = b.astype("float32")
    na = a / (np.linalg.norm(a) + 1e-12)
    nb = b / (np.linalg.norm(b) + 1e-12)
    return float(np.dot(na, nb))

# --- Main scanning logic for videos ---
def scan_video_index(video_root: Path, max_frames_per_video: int = 80, dedup_threshold: float = 0.985):
    """
    Walk video_root for video files, extract frames, embed, dedup, store .npy, update DB.
    """
    init_video_db()
    known = get_known_videos()
    new_count = 0
    next_aid = get_next_annoy_id()
    exts = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
    for p in video_root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        s = str(p)
        info = known.get(s)
        if info and abs(info["mtime"] - mtime) < 0.001:
            continue  # unchanged
        # new or changed video
        print("🔎 Video scan: processing", s)
        tmpdir, frames = extract_frames_scene_or_sample(s, max_frames_per_video)
        if not frames:
            try:
                tmpdir.rmdir()
            except:
                pass
            add_or_update_video(s, mtime)
            continue

        # embed frames one-by-one, dedup against last stored frame for this video
        video_id = None
        conn = _get_conn()
        cur = conn.execute("SELECT id FROM videos WHERE path = ?", (s,))
        row = cur.fetchone()
        if row:
            video_id = row["id"]
        else:
            # insert video row
            conn.execute("INSERT INTO videos (path, mtime) VALUES (?, ?)", (s, mtime))
            conn.commit()
            cur = conn.execute("SELECT id FROM videos WHERE path = ?", (s,))
            row = cur.fetchone()
            video_id = row["id"]
        conn.close()

        # get last embedding vector saved for this video (to dedup)
        last_vec = None
        conn = _get_conn()
        cur = conn.execute("SELECT annoy_id FROM frames WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,))
        rv = cur.fetchone()
        conn.close()
        if rv and rv["annoy_id"]:
            import numpy as np
            try:
                last_vec = np.load(str(VIDEO_EMBED_DIR / f"{rv['annoy_id']}.npy"))
            except Exception:
                last_vec = None

        # iterate frames
        for img_path, ts in frames:
            try:
                # embed using shared CLIP image encoder (expects Path)
                from unimain import embed_image_file  # or import the function from where it's defined
                vec = embed_image_file(Path(img_path))
            except Exception as e:
                print("embed failed for frame:", e)
                continue
            # dedup
            if last_vec is not None:
                sim = cosine_sim(vec, last_vec)
                if sim >= dedup_threshold:
                    # skip storing duplicate frame
                    continue
            # persist vector
            aid = next_aid
            import numpy as np
            np.save(str(VIDEO_EMBED_DIR / f"{aid}.npy"), vec)
            add_frame(video_id, ts if ts is not None else -1.0, aid)
            last_vec = vec
            next_aid += 1
            new_count += 1

        # cleanup tmpdir
        try:
            # remove extracted files
            for f in Path(tmpdir).glob("*"):
                try:
                    f.unlink()
                except:
                    pass
            Path(tmpdir).rmdir()
        except Exception:
            pass

        # update video mtime (mark processed)
        add_or_update_video(s, mtime)

    # decide rebuild
    if new_count > 0:
        print("🔔 Video scan added", new_count, "new vectors")
        # if many new vectors, do a rebuild
        if new_count >= 8:
            def _bg_rebuild():
                try:
                    rebuild_video_annoy_index(all_video_vectors_iterator)
                except Exception as e:
                    print("video rebuild failed:", e)
            threading.Thread(target=_bg_rebuild, daemon=True).start()
            global _video_annoy_needs_rebuild
            _video_annoy_needs_rebuild = True
        else:
            # schedule small rebuild (same as images approach)
            threading.Thread(target=lambda: rebuild_video_annoy_index(all_video_vectors_iterator), daemon=True).start()
            _video_annoy_needs_rebuild = True

    return {"status": "ok", "new_vectors": new_count}

# --- Video search ---
def search_videos(query: str, top_k: int = 10):
    """
    Load video annoy on demand, embed text with CLIP, query Annoy, then unload to free RAM.
    Returns list of {'video_path': ..., 'annoy_id': ..., 'score': ...}
    """
    global _video_annoy_needs_rebuild
    init_video_db()
    # ensure index available or rebuild if needed
    if not ensure_video_annoy_loaded():
        return {"error": "annoy_unavailable"}

    # if index missing but frames exist, rebuild sync (cheap for small)
    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) as cnt FROM frames WHERE annoy_id IS NOT NULL")
    cnt = cur.fetchone()[0]
    conn.close()
    if cnt > 0:
        if (not VIDEO_ANNOY_INDEX.exists()) or _video_annoy_needs_rebuild:
            try:
                rebuild_video_annoy_index(all_video_vectors_iterator)
            except Exception as e:
                print("Rebuild on-demand failed:", e)

    # embed query
    try:
        from unimain import embed_text_with_clip
        qvec = embed_text_with_clip(query)
    except Exception as e:
        return {"error": f"embed_failed: {e}"}

    # load index, query, then unload
    global _video_annoy
    if _video_annoy is None:
        # load as necessary
        if not ensure_video_annoy_loaded() or _video_annoy is None:
            return {"error": "annoy_not_loaded"}

    try:
        ids, dists = _video_annoy.get_nns_by_vector(qvec.tolist(), top_k, include_distances=True)
    except Exception as e:
        return {"error": f"annoy_query_failed: {e}"}

    # map ids to video path
    conn = _get_conn()
    hits = []
    video_scores = {}
    for aid, dist in zip(ids, dists):
        cur = conn.execute(
            "SELECT v.path as path FROM frames f "
            "JOIN videos v ON f.video_id = v.id "
            "WHERE f.annoy_id = ?", (aid,)
        )
        row = cur.fetchone()
        if not row:
            continue

        cos_sim = 1.0 - (dist / 2.0)

        if cos_sim < 0.15:
            continue

        path = row["path"]

        # keep best score per video
        if path not in video_scores:
            video_scores[path] = cos_sim
        else:
            video_scores[path] = max(video_scores[path], cos_sim)

    conn.close()

    # convert to list
    hits = [
        {"video_path": path, "score": score}
        for path, score in video_scores.items()
    ]

    # sort by score
    hits = sorted(hits, key=lambda x: x["score"], reverse=True)

    # keep top 2 only
    hits = hits[:2]

    # unload index to free memory
    try:
        unload_video_annoy()
    except Exception:
        pass

    return {"hits": hits}
