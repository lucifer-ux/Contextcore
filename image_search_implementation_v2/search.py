# image_search_implementation_v2/search.py
from __future__ import annotations

import re
import shutil
from importlib.util import find_spec

from rapidfuzz import fuzz

from .annoy_store import get_annoy_status, search_annoy
from .config import ANN_TOPK, CLIP_MODEL_NAME, FTS_TOPK, FUZZY_FILENAME_THRESHOLD, UNION_LIMIT
from .db import all_filenames, get_conn, get_metadata_by_annoy_ids, get_metadata_by_ids, query_fts


def _tokens(q: str):
    return re.findall(r"\b\w+\b", q.lower())


def _fts_query(q: str):
    tokens = _tokens(q)
    if not tokens:
        return []
    q_f = " OR ".join(t + "*" for t in tokens)
    return query_fts(q_f, limit=FTS_TOPK)


def _best_filename_score(tokens: list[str], filename: str) -> float:
    fname = (filename or "").lower()
    best = 0
    for t in tokens:
        s = fuzz.partial_ratio(t, fname)
        if s > best:
            best = s
    return best / 100.0


def _normalized_filename_text(filename: str) -> str:
    name = (filename or "").lower()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = re.sub(r"[_\-\(\)\[\]\.]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _query_filename_similarity(query: str, filename: str) -> float:
    q = re.sub(r"\s+", " ", (query or "").lower()).strip()
    f = _normalized_filename_text(filename)
    if not q or not f:
        return 0.0
    # Whole-string similarity so unrelated names don't get a filename boost.
    return fuzz.ratio(q, f) / 100.0


def _image_capabilities() -> dict:
    ocr_pkg = find_spec("pytesseract") is not None
    ocr_bin = shutil.which("tesseract") is not None
    annoy_status = get_annoy_status()
    return {
        "ocr_available": bool(ocr_pkg and ocr_bin),
        "ocr_package_installed": bool(ocr_pkg),
        "ocr_binary_installed": bool(ocr_bin),
        "annoy_installed": bool(annoy_status.get("installed")),
        "annoy_index_ready": bool(annoy_status.get("ready")),
        "annoy_needs_rebuild": bool(annoy_status.get("needs_rebuild")),
        "semantic_backend_available": bool(annoy_status.get("ready")),
        "semantic_backend": "annoy_sqlite",
    }


def _semantic_ann_hits(query: str, top_k: int) -> dict[int, float]:
    annoy_status = get_annoy_status()
    if not annoy_status.get("installed"):
        return {}
    try:
        from .embedder import load_clip
        import torch

        model, processor = load_clip(CLIP_MODEL_NAME)
        inputs = processor(text=[query], return_tensors="pt", padding=True)
        inputs = {k: v.to(torch.device("cpu")) for k, v in inputs.items()}
        with torch.no_grad():
            text_feats = model.get_text_features(**inputs)
        if hasattr(text_feats, "pooler_output") and text_feats.pooler_output is not None:
            text_feats = text_feats.pooler_output
        elif hasattr(text_feats, "last_hidden_state") and text_feats.last_hidden_state is not None:
            text_feats = text_feats.last_hidden_state[:, 0, :]
        elif isinstance(text_feats, (tuple, list)) and text_feats:
            text_feats = text_feats[0]
        text_feats = text_feats / (text_feats.norm(dim=-1, keepdim=True) + 1e-12)
        query_vec = text_feats.squeeze(0).cpu().numpy()
        ann_rows = search_annoy(query_vec, top_k=top_k)
    except Exception as e:
        print("ann semantic query failed:", e)
        return {}

    by_annoy = {}
    for row in ann_rows:
        by_annoy[int(row["annoy_id"])] = max(0.0, float(row.get("semantic_score", 0.0)))

    if not by_annoy:
        return {}

    meta_by_annoy = get_metadata_by_annoy_ids(list(by_annoy.keys()))
    by_image_id: dict[int, float] = {}
    for annoy_id, sem_score in by_annoy.items():
        meta = meta_by_annoy.get(int(annoy_id))
        if not meta:
            continue
        image_id = int(meta["id"])
        prev = by_image_id.get(image_id, 0.0)
        if sem_score > prev:
            by_image_id[image_id] = sem_score
    return by_image_id


def search(query: str, top_k: int = 20):
    q = query.strip()
    if not q:
        return []

    tokens = _tokens(q)
    capabilities = _image_capabilities()

    # Exact filename shortcut.
    conn = get_conn()
    row = conn.execute(
        """
        SELECT
            i.id,
            i.path,
            i.filename,
            COALESCE(i.ocr_text, '') AS ocr_text
        FROM images i
        WHERE LOWER(i.filename) = ?
        LIMIT 1
        """,
        (q.lower(),),
    ).fetchone()
    conn.close()
    if row:
        ocr_text = (row["ocr_text"] or "").strip()
        final_score = 5.0
        return [
            {
                "path": row["path"],
                "filename": row["filename"],
                "score": final_score,
                "final_score": final_score,
                "semantic_score": 0.0,
                "ocr_score": 0.0,
                "filename_score": 1.0,
                "match_type": "filename",
                "ocr_text": ocr_text[:600] if ocr_text else "",
                "ocr_snippet": "",
                "capabilities": capabilities,
            }
        ]

    fts_rows = _fts_query(q)
    fts_ids = [int(r["id"]) for r in fts_rows]
    fts_map = {int(r["id"]): float(r["score"]) for r in fts_rows}
    fts_snippet_map: dict[int, str] = {}
    sem_map = _semantic_ann_hits(q, top_k=ANN_TOPK)

    union = []
    seen = set()
    for image_id in fts_ids + list(sem_map.keys()):
        if image_id in seen:
            continue
        seen.add(image_id)
        union.append(image_id)
        if len(union) >= UNION_LIMIT:
            break

    results = []
    if not union:
        rows = all_filenames()
        for r in rows:
            filename_score = _best_filename_score(tokens, r["filename"])
            if filename_score * 100.0 < FUZZY_FILENAME_THRESHOLD:
                continue
            final_score = 1.8 * filename_score
            results.append(
                {
                    "path": r["path"],
                    "filename": r["filename"],
                    "score": final_score,
                    "final_score": final_score,
                    "semantic_score": 0.0,
                    "ocr_score": 0.0,
                    "filename_score": filename_score,
                "match_type": "filename",
                "ocr_text": "",
                "ocr_snippet": "",
                "capabilities": capabilities,
                }
            )
        results.sort(key=lambda x: x["final_score"], reverse=True)
        return results[:top_k]

    metas = get_metadata_by_ids(union)
    for idx in union:
        meta = metas.get(idx)
        if not meta:
            continue

        filename = meta.get("filename", "")
        ocr_text = (meta.get("ocr_text") or "").strip()
        semantic_score = max(0.0, sem_map.get(idx, 0.0))
        ocr_score = (1.0 / (1.0 + fts_map[idx])) if idx in fts_map else 0.0
        filename_score = _best_filename_score(tokens, filename)
        filename_similarity = _query_filename_similarity(q, filename)

        # Filename weighting only for exact / near-exact spelling.
        if filename_similarity >= 0.97:
            filename_bonus = 1.0
        elif filename_similarity >= 0.88:
            filename_bonus = filename_similarity
        else:
            filename_bonus = 0.0

        final_score = 0.0
        final_score += 3.0 * semantic_score
        final_score += 1.4 * ocr_score
        final_score += 1.8 * filename_bonus

        has_sem = semantic_score > 0
        has_ocr = ocr_score > 0
        has_filename = filename_bonus > 0
        if has_sem and (has_ocr or has_filename):
            match_type = "hybrid"
        elif has_sem:
            match_type = "semantic"
        elif has_filename:
            match_type = "filename"
        else:
            match_type = "ocr"

        results.append(
            {
                "path": meta["path"],
                "filename": filename,
                "score": final_score,
                "final_score": final_score,
                "semantic_score": semantic_score,
                "ocr_score": ocr_score,
                "filename_score": filename_score,
                "match_type": match_type,
                "ocr_text": ocr_text[:600] if ocr_text else "",
                "ocr_snippet": fts_snippet_map.get(idx, "") or (ocr_text[:180] if ocr_text else ""),
                "capabilities": capabilities,
            }
        )

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:top_k]
