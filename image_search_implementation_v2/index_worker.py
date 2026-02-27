# image_search_implementation_v2/index_worker.py
"""
Usage:
  python -m image_search_implementation_v2.index_worker --file /path/to/img.jpg
  python -m image_search_implementation_v2.index_worker --scan
"""
import argparse
from pathlib import Path
from .config import BASE_DIR, IMAGE_FOLDER, CLIP_MODEL_NAME, VECTOR_DIM
from .db import init_db, upsert_image
from .ocr import extract_ocr_from_image
from .embedder import embed_image
from .vector_store import ensure_collection, upsert_vectors, qdrant_available
import time

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".pdf"}

def index_file(p: Path):
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
    if not changed:
        print("unchanged, skipped:", p)
        return True
    # compute embedding (may be slow; done in worker)
    emb = embed_image(p, CLIP_MODEL_NAME)
    if emb is not None and qdrant_available():
        # upsert to qdrant (single)
        upsert_vectors([{"id": img_id, "vector": emb, "payload": {"path": str(p), "filename": p.name}}])
    print("done:", p)
    return True

def full_scan():
    init_db()
    base = Path(BASE_DIR) / IMAGE_FOLDER
    total = 0
    if not base.exists():
        print("no image folder:", base)
        return
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        ok = index_file(p)
        if ok:
            total += 1
    print("indexed total:", total)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str)
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()
    init_db()
    ensure_collection()
    if args.file:
        index_file(Path(args.file))
    elif args.scan:
        full_scan()
    else:
        print("use --file or --scan")

if __name__ == "__main__":
    main()
