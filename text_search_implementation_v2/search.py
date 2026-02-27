# text_search_implementation_v2/search.py
from typing import List, Dict, Any
from text_search_implementation_v2.db import init_db, query_fts, get_file_metadata_by_ids
from rapidfuzz import fuzz
import re

# tunables
FTS_CANDIDATE_LIMIT = 50
FUZZY_FILENAME_THRESHOLD = 70  # adjust if needed
EXACT_FILENAME_BOOST = 5.0
FUZZY_FILENAME_BOOST = 3.0
FTS_SCORE_WEIGHT = 1.0

def _normalize_query_for_fts(q: str) -> str:
    tokens = re.findall(r"\b\w+\b", q)
    if not tokens:
        return ""
    return " OR ".join(t + "*" for t in tokens)

class TextSearchEngineV2:
    def __init__(self):
        # ensure DB exists
        init_db()

    def search(self, query: str, categories=None, top_k: int = 20):

        if not query or not query.strip():
            return []

        q_norm = query.strip().lower()
        tokens = re.findall(r"\b\w+\b", q_norm)

        # --------------------------------
        # 1) Exact filename match
        # --------------------------------
        from text_search_implementation_v2.db import get_conn
        conn = get_conn()
        cur = conn.execute(
            "SELECT id, path, filename, category FROM files WHERE LOWER(filename) = ? LIMIT 1",
            (q_norm,)
        )
        row = cur.fetchone()
        conn.close()

        if row:
            return [{
                "path": row["path"],
                "filename": row["filename"],
                "category": row["category"],
                "score": EXACT_FILENAME_BOOST
            }]

        # --------------------------------
        # 2) FTS search (OR mode)
        # --------------------------------
        match_q = " OR ".join(t + "*" for t in tokens)

        rows = query_fts(match_q, limit=FTS_CANDIDATE_LIMIT) if tokens else []

        ids = [r["id"] for r in rows]
        id_to_meta = get_file_metadata_by_ids(ids)

        results = []

        for r in rows:
            fid = r["id"]
            meta = id_to_meta.get(fid)
            if not meta:
                continue

            base = 1.0 / (1.0 + float(r["score"]))

            # fuzzy filename boost
            fname = meta["filename"].lower()

            best_token_score = 0
            for t in tokens:
                score = fuzz.partial_ratio(t, fname)
                best_token_score = max(best_token_score, score)

            final_score = base

            if best_token_score >= FUZZY_FILENAME_THRESHOLD:
                final_score += FUZZY_FILENAME_BOOST * (best_token_score / 100.0)

            results.append({
                "path": meta["path"],
                "filename": meta["filename"],
                "category": meta["category"],
                "score": final_score
            })

        # --------------------------------
        # 3) Fallback fuzzy if FTS empty
        # --------------------------------
        if not results:
            conn = get_conn()
            cur = conn.execute("SELECT path, filename, category FROM files")
            all_files = cur.fetchall()
            conn.close()

            for row in all_files:
                fname = row["filename"].lower()
                best_token_score = 0
                for t in tokens:
                    score = fuzz.partial_ratio(t, fname)
                    best_token_score = max(best_token_score, score)

                if best_token_score >= FUZZY_FILENAME_THRESHOLD:
                    results.append({
                        "path": row["path"],
                        "filename": row["filename"],
                        "category": row["category"],
                        "score": best_token_score / 100.0
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

