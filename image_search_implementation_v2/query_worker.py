# image_search_implementation_v2/query_worker.py
"""
Small CLI worker that:
- loads CLIP (text encoder) once,
- computes query vector,
- asks Qdrant for ANN results,
- prints JSON to stdout and exits.

This process exits after printing, freeing model memory.
"""

import argparse
import json
import sys
import numpy as np

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--qdrant-url", type=str, default=None)
    args = parser.parse_args()

    # Lazy imports (so worker stays small until invoked)
    try:
        from .config import CLIP_MODEL_NAME
        from .vector_store import qdrant_available, search_vectors, get_client
        from .embedder import load_clip
    except Exception as e:
        print(json.dumps({"error": f"internal_import_failed: {e}"}))
        sys.exit(2)

    # If Qdrant unavailable, return empty or error
    if not qdrant_available():
        print(json.dumps({"error": "qdrant_unavailable"}))
        sys.exit(0)

    # Load CLIP model (text encoder) - on CPU
    try:
        model, processor = load_clip(CLIP_MODEL_NAME)
    except Exception as e:
        print(json.dumps({"error": f"load_clip_failed: {e}"}))
        sys.exit(2)

    # compute text embedding
    try:
        import torch
        inputs = processor(text=[args.query], return_tensors="pt", padding=True)
        inputs = {k: v.to(torch.device("cpu")) for k, v in inputs.items()}
        with torch.no_grad():
            text_feats = model.get_text_features(**inputs)
        text_feats = text_feats / text_feats.norm(dim=-1, keepdim=True)
        qvec = text_feats.squeeze(0).cpu().numpy().astype(np.float32)
    except Exception as e:
        print(json.dumps({"error": f"embed_failed: {e}"}))
        sys.exit(2)

    # ANN search
    try:
        hits = search_vectors(qvec, top_k=args.topk)
        # hits is [{"id":..., "score":..., "payload": {...}}, ...]
        print(json.dumps({"hits": hits}))
        sys.exit(0)
    except Exception as e:
        print(json.dumps({"error": f"ann_search_failed: {e}"}))
        sys.exit(2)

if __name__ == "__main__":
    main()
