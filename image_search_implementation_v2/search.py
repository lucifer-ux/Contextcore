# image_search_implementation_v2/search.py
from .db import query_fts, get_metadata_by_ids, all_filenames
from .vector_store import search_vectors, qdrant_available
from rapidfuzz import fuzz
import re
from .config import FTS_TOPK, ANN_TOPK, UNION_LIMIT, FUZZY_FILENAME_THRESHOLD

def _tokens(q: str):
    return re.findall(r"\b\w+\b", q.lower())

def _fts_query(q: str):
    tokens = _tokens(q)
    if not tokens:
        return []
    # OR query so we don't require all tokens
    q_f = " OR ".join(t + "*" for t in tokens)
    return query_fts(q_f, limit=FTS_TOPK)

def search(query: str, top_k: int = 20):
    q = query.strip()
    if not q:
        return []

    tokens = _tokens(q)

    # EXACT filename shortcut
    # small direct query
    from .db import get_conn
    conn = get_conn()
    cur = conn.execute("SELECT id, path, filename, mtime FROM images WHERE LOWER(filename) = ? LIMIT 1", (q.lower(),))
    row = cur.fetchone()
    conn.close()
    if row:
        return [{
            "path": row["path"],
            "filename": row["filename"],
            "score": 5.0
        }]

    # parallel-ish: get FTS candidates
    fts_rows = _fts_query(q)

    fts_ids = [r["id"] for r in fts_rows]

    # ANN candidates if qdrant available
    ann_rows = []
    if qdrant_available():
        # we need to compute a query vector. We'll try to use CLIP text embedding via the same embedder
        try:
            from .embedder import load_clip
            model, processor = load_clip(__import__("image_search_implementation_v2.config", fromlist=["CLIP_MODEL_NAME"]).CLIP_MODEL_NAME)
            # workaround: use processor to get text embedding via model.get_text_features
            inputs = processor(text=[q], return_tensors="pt", padding=True)
            import torch
            inputs = {k: v.to(torch.device("cpu")) for k, v in inputs.items()}
            with torch.no_grad():
                text_feats = model.get_text_features(**inputs)
            text_feats = text_feats / text_feats.norm(dim=-1, keepdim=True)
            query_vec = text_feats.squeeze(0).cpu().numpy()
            ann_rows = search_vectors(query_vec, top_k=ANN_TOPK)
        except Exception as e:
            print("ann query failed, skipping ANN:", e)
            ann_rows = []
    else:
        ann_rows = []

    ann_ids = [r["id"] for r in ann_rows]

    # union candidate ids
    union = []
    seen = set()
    for i in fts_ids + ann_ids:
        if i not in seen:
            union.append(i)
            seen.add(i)
        if len(union) >= UNION_LIMIT:
            break

    # if no union candidates, run filename fuzzy fallback across all filenames
    results = []
    if not union:
        rows = all_filenames()
        for r in rows:
            fname = r["filename"].lower()
            best = 0
            for t in tokens:
                s = fuzz.partial_ratio(t, fname)
                if s > best:
                    best = s
            if best >= FUZZY_FILENAME_THRESHOLD:
                results.append({
                    "path": r["path"],
                    "filename": r["filename"],
                    "score": best / 100.0
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # fetch metadata
    metas = get_metadata_by_ids(union)

    # map scores
    fts_map = {int(r["id"]): float(r["score"]) for r in fts_rows}
    ann_map = {int(r["id"]): float(r["score"]) for r in ann_rows}

    for idx in union:
        meta = metas.get(idx)
        if not meta:
            continue
        lex_score = 1.0 / (1.0 + fts_map.get(idx, 10.0))  # convert bm25->0..1; default 10.0 -> small
        sem_score = ann_map.get(idx, 0.0)
        # map sem_score: qdrant returns similarity-like (higher better). Keep as-is but clamp.
        fname = meta["filename"].lower()
        best_token = 0
        for t in tokens:
            s = fuzz.partial_ratio(t, fname)
            if s > best_token:
                best_token = s
        fname_score = best_token / 100.0

        # blended score (tweak weights as needed)
        final = 3.0 * (1.0 if fname == query.lower() else 0.0)
        final += 2.5 * fname_score
        final += 1.0 * lex_score
        final += 1.5 * sem_score

        results.append({
            "path": meta["path"],
            "filename": meta["filename"],
            "score": final
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
