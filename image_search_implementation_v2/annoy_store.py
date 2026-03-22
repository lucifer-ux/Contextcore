# image_search_implementation_v2/annoy_store.py
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .config import ANNOY_INDEX_PATH, ANNOY_N_TREES, ANNOY_STATE_PATH, VECTOR_DIM
from .db import count_vector_ready_images, iter_annoy_vectors

_LOCK = threading.Lock()
_ANNOY_INDEX = None
_ANNOY_LOADED = False


def annoy_installed() -> bool:
    try:
        import annoy  # noqa: F401
        return True
    except Exception:
        return False


def _default_state() -> dict[str, Any]:
    return {"needs_rebuild": False, "last_rebuild_at": None}


def load_state() -> dict[str, Any]:
    if not ANNOY_STATE_PATH.exists():
        return _default_state()
    try:
        data = json.loads(ANNOY_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
        return {
            "needs_rebuild": bool(data.get("needs_rebuild", False)),
            "last_rebuild_at": data.get("last_rebuild_at"),
        }
    except Exception:
        return _default_state()


def save_state(state: dict[str, Any]) -> None:
    ANNOY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANNOY_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def mark_dirty() -> None:
    state = load_state()
    state["needs_rebuild"] = True
    save_state(state)


def clear_dirty() -> None:
    state = load_state()
    state["needs_rebuild"] = False
    state["last_rebuild_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


def _build_empty_index():
    from annoy import AnnoyIndex

    global _ANNOY_INDEX, _ANNOY_LOADED
    _ANNOY_INDEX = AnnoyIndex(VECTOR_DIM, "angular")
    _ANNOY_LOADED = True


def _load_index_from_disk() -> bool:
    if not annoy_installed():
        return False

    from annoy import AnnoyIndex

    global _ANNOY_INDEX, _ANNOY_LOADED
    if not ANNOY_INDEX_PATH.exists():
        _build_empty_index()
        return False

    ai = AnnoyIndex(VECTOR_DIM, "angular")
    ai.load(str(ANNOY_INDEX_PATH))
    _ANNOY_INDEX = ai
    _ANNOY_LOADED = True
    return True


def rebuild_annoy_index() -> dict[str, Any]:
    with _LOCK:
        if not annoy_installed():
            return {
                "ok": False,
                "error": "annoy_not_installed",
                "indexed_vectors": 0,
                "index_exists": ANNOY_INDEX_PATH.exists(),
            }

        from annoy import AnnoyIndex

        ai = AnnoyIndex(VECTOR_DIM, "angular")
        count = 0
        missing_embeddings = 0

        for row in iter_annoy_vectors():
            annoy_id = row["annoy_id"]
            emb_path = (row["embedding_path"] or "").strip()
            if annoy_id is None or not emb_path:
                continue
            p = Path(emb_path)
            if not p.exists():
                missing_embeddings += 1
                continue
            try:
                vec = np.load(str(p)).astype(np.float32).reshape(-1)
                if vec.shape[0] != VECTOR_DIM:
                    missing_embeddings += 1
                    continue
                ai.add_item(int(annoy_id), vec.tolist())
                count += 1
            except Exception:
                missing_embeddings += 1

        global _ANNOY_INDEX, _ANNOY_LOADED
        if count > 0:
            ai.build(ANNOY_N_TREES)
            ai.save(str(ANNOY_INDEX_PATH))
            _ANNOY_INDEX = ai
            _ANNOY_LOADED = True
        else:
            if ANNOY_INDEX_PATH.exists():
                ANNOY_INDEX_PATH.unlink(missing_ok=True)
            _build_empty_index()

        clear_dirty()
        return {
            "ok": True,
            "indexed_vectors": int(count),
            "missing_embeddings": int(missing_embeddings),
            "index_exists": ANNOY_INDEX_PATH.exists(),
        }


def ensure_annoy_ready() -> dict[str, Any]:
    state = load_state()
    if state.get("needs_rebuild") or not ANNOY_INDEX_PATH.exists():
        return rebuild_annoy_index()

    global _ANNOY_LOADED
    if not _ANNOY_LOADED:
        _load_index_from_disk()

    return {
        "ok": True,
        "indexed_vectors": int(count_vector_ready_images()),
        "index_exists": ANNOY_INDEX_PATH.exists(),
    }


def search_annoy(query_vector: np.ndarray, top_k: int = 50) -> list[dict[str, float]]:
    if not annoy_installed():
        return []

    ensure_annoy_ready()
    if _ANNOY_INDEX is None:
        return []

    qvec = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    if qvec.shape[0] != VECTOR_DIM:
        return []

    try:
        ids, dists = _ANNOY_INDEX.get_nns_by_vector(
            qvec.tolist(),
            max(1, int(top_k)),
            include_distances=True,
        )
    except Exception:
        return []

    out: list[dict[str, float]] = []
    for aid, dist in zip(ids, dists):
        semantic_score = max(0.0, float(1.0 - float(dist) / 2.0))
        out.append(
            {
                "annoy_id": int(aid),
                "distance": float(dist),
                "semantic_score": semantic_score,
            }
        )
    return out


def get_annoy_status() -> dict[str, Any]:
    state = load_state()
    vector_ready = int(count_vector_ready_images())
    index_exists = ANNOY_INDEX_PATH.exists()
    needs_rebuild = bool(state.get("needs_rebuild", False))
    installed = annoy_installed()
    ready = bool(installed and index_exists and not needs_rebuild and vector_ready > 0)
    return {
        "installed": installed,
        "index_exists": index_exists,
        "needs_rebuild": needs_rebuild,
        "vector_ready_images": vector_ready,
        "ready": ready,
        "last_rebuild_at": state.get("last_rebuild_at"),
    }
