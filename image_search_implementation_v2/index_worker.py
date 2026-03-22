# image_search_implementation_v2/index_worker.py
"""
Usage:
  python -m image_search_implementation_v2.index_worker --file /path/to/img.jpg
  python -m image_search_implementation_v2.index_worker --scan
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np

from .annoy_store import get_annoy_status, mark_dirty, rebuild_annoy_index
from .config import BASE_DIR, CLIP_MODEL_NAME, EMBEDDINGS_DIR, IMAGE_FOLDER
from .db import allocate_annoy_id, init_db, needs_embedding, update_embedding_meta, upsert_image
from .embedder import embed_image
from .ocr import extract_ocr_from_image

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".pdf"}


def _embedding_hash(vec: np.ndarray) -> str:
    return hashlib.sha256(vec.astype(np.float32).tobytes()).hexdigest()


def index_file(p: Path) -> bool:
    p = p.resolve()
    if not p.exists() or not p.is_file():
        print("not found:", p)
        return False

    ext = p.suffix.lower()
    if ext not in IMAGE_EXTS:
        print("skip (ext):", p)
        return False

    print("indexing:", p)
    ocr_text = extract_ocr_from_image(p)
    mtime = p.stat().st_mtime
    changed, img_id = upsert_image(str(p), p.name, mtime, ocr_text)

    # PDFs are OCR/lexical searchable but do not go through CLIP image embeddings.
    if ext == ".pdf":
        print("indexed metadata only (pdf):", p)
        return True

    must_embed = changed or needs_embedding(img_id)
    if not must_embed:
        print("unchanged, skipped:", p)
        return True

    emb = embed_image(p, CLIP_MODEL_NAME)
    if emb is None:
        # Keep OCR/filename index even when semantic embedding is unavailable.
        print("indexed metadata only (no embedding):", p)
        return True

    emb = np.asarray(emb, dtype=np.float32).reshape(-1)
    annoy_id = allocate_annoy_id(img_id)
    emb_path = EMBEDDINGS_DIR / f"{annoy_id}.npy"
    np.save(str(emb_path), emb)

    update_embedding_meta(
        image_id=img_id,
        annoy_id=annoy_id,
        embedding_path=str(emb_path),
        embedding_hash=_embedding_hash(emb),
    )
    mark_dirty()
    print("done:", p, f"(annoy_id={annoy_id})")
    return True


def finalize_indexing(rebuild: bool = True) -> dict:
    status = get_annoy_status()
    if rebuild and status.get("needs_rebuild"):
        return rebuild_annoy_index()
    return {"ok": True, "indexed_vectors": int(status.get("vector_ready_images", 0))}


def full_scan():
    init_db()
    base = Path(BASE_DIR) / IMAGE_FOLDER
    total = 0
    if not base.exists():
        print("no image folder:", base)
        return {"indexed_files": 0, "annoy": finalize_indexing(rebuild=True)}
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        ok = index_file(p)
        if ok:
            total += 1
    annoy_result = finalize_indexing(rebuild=True)
    print("indexed total:", total)
    return {"indexed_files": total, "annoy": annoy_result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str)
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()
    init_db()
    if args.file:
        index_file(Path(args.file))
        print(finalize_indexing(rebuild=True))
    elif args.scan:
        print(full_scan())
    else:
        print("use --file or --scan")


if __name__ == "__main__":
    main()
