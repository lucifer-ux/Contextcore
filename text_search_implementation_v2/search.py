# text_search_implementation_v2/search.py
import base64
import json
import re
from typing import Any

from text_search_implementation_v2.db import (
    get_file_metadata_by_ids,
    get_fts_content_by_ids,
    init_db,
    query_fts,
)
from rapidfuzz import fuzz

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

    def _split_chunks(self, text: str, chunk_chars: int, chunk_overlap: int) -> list[dict[str, Any]]:
        if not text:
            return []
        step = max(1, chunk_chars - chunk_overlap)
        chunks: list[dict[str, Any]] = []
        i = 0
        idx = 0
        while i < len(text):
            end = min(len(text), i + chunk_chars)
            chunk = text[i:end].strip()
            if chunk:
                chunks.append({"index": idx, "start": i, "end": end, "text": chunk})
                idx += 1
            if end >= len(text):
                break
            i += step
        return chunks

    def _best_chunk(self, text: str, tokens: list[str], chunk_chars: int, chunk_overlap: int) -> tuple[dict[str, Any] | None, int]:
        chunks = self._split_chunks(text, chunk_chars, chunk_overlap)
        if not chunks:
            return None, 0
        if not tokens:
            return chunks[0], len(chunks)

        def _chunk_score(c: dict[str, Any]) -> int:
            t = c["text"].lower()
            return sum(t.count(tok) for tok in tokens)

        best = max(chunks, key=_chunk_score)
        return best, len(chunks)

    def _encode_chunk_id(self, file_id: int, chunk_index: int, chunk_chars: int, chunk_overlap: int) -> str:
        payload = {
            "fid": int(file_id),
            "idx": int(chunk_index),
            "cc": int(chunk_chars),
            "ov": int(chunk_overlap),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_chunk_id(self, chunk_id: str) -> dict[str, int]:
        pad = "=" * ((4 - len(chunk_id) % 4) % 4)
        data = base64.urlsafe_b64decode((chunk_id + pad).encode("ascii"))
        obj = json.loads(data.decode("utf-8"))
        return {
            "fid": int(obj["fid"]),
            "idx": int(obj["idx"]),
            "cc": int(obj["cc"]),
            "ov": int(obj["ov"]),
        }

    def search(
        self,
        query: str,
        categories=None,
        top_k: int = 20,
        include_metadata: bool = False,
        chunk_chars: int = 900,
        chunk_overlap: int = 120,
        exclude_sources: set[str] | None = None,
    ):

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
        id_to_content = get_fts_content_by_ids(ids)
        excluded = {str(p) for p in (exclude_sources or set())}

        for r in rows:
            fid = r["id"]
            meta = id_to_meta.get(fid)
            if not meta:
                continue
            if meta["path"] in excluded:
                continue

            base = -float(r["score"])

            # fuzzy filename boost
            fname = meta["filename"].lower()

            best_token_score = 0
            for t in tokens:
                score = fuzz.partial_ratio(t, fname)
                best_token_score = max(best_token_score, score)

            final_score = base

            if best_token_score >= FUZZY_FILENAME_THRESHOLD:
                final_score += FUZZY_FILENAME_BOOST * (best_token_score / 100.0)

            content = id_to_content.get(fid, "")
            best_chunk, total_chunks = self._best_chunk(content, tokens, chunk_chars, chunk_overlap)
            if not best_chunk:
                continue

            item = {
                "path": meta["path"],
                "category": meta["category"],
                "score": final_score,
                "chunk": best_chunk["text"],
                "chunk_id": self._encode_chunk_id(fid, best_chunk["index"], chunk_chars, chunk_overlap),
                "chunk_index": best_chunk["index"],
                "chunk_total": total_chunks,
            }
            if include_metadata:
                item["filename"] = meta["filename"]
                item["file_id"] = fid
            results.append(item)

        # --------------------------------
        # 3) Fallback fuzzy if FTS empty
        # --------------------------------
        if not results:
            conn = get_conn()
            cur = conn.execute("SELECT id, path, filename, category FROM files")
            all_files = cur.fetchall()
            conn.close()

            for row in all_files:
                if row["path"] in excluded:
                    continue
                fname = row["filename"].lower()
                best_token_score = 0
                for t in tokens:
                    score = fuzz.partial_ratio(t, fname)
                    best_token_score = max(best_token_score, score)

                if best_token_score >= FUZZY_FILENAME_THRESHOLD:
                    content = get_fts_content_by_ids([row["id"]]).get(row["id"], "")
                    best_chunk, total_chunks = self._best_chunk(content, tokens, chunk_chars, chunk_overlap)
                    if not best_chunk:
                        continue
                    item = {
                        "path": row["path"],
                        "category": row["category"],
                        "score": best_token_score / 100.0,
                        "chunk": best_chunk["text"],
                        "chunk_id": self._encode_chunk_id(row["id"], best_chunk["index"], chunk_chars, chunk_overlap),
                        "chunk_index": best_chunk["index"],
                        "chunk_total": total_chunks,
                    }
                    if include_metadata:
                        item["filename"] = row["filename"]
                        item["file_id"] = row["id"]
                    results.append(item)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_neighbors(
        self,
        chunk_id: str,
        direction: str = "next",
        count: int = 1,
    ) -> dict[str, Any]:
        data = self._decode_chunk_id(chunk_id)
        fid = data["fid"]
        idx = data["idx"]
        chunk_chars = data["cc"]
        chunk_overlap = data["ov"]

        meta = get_file_metadata_by_ids([fid]).get(fid)
        if not meta:
            return {"ok": False, "error": "file_not_found"}

        content = get_fts_content_by_ids([fid]).get(fid, "")
        chunks = self._split_chunks(content, chunk_chars, chunk_overlap)
        if not chunks:
            return {"ok": False, "error": "no_chunks"}

        direction = direction.lower().strip()
        if direction not in {"next", "prev"}:
            return {"ok": False, "error": "invalid_direction"}

        out = []
        step = 1 if direction == "next" else -1
        cur = idx
        for _ in range(max(1, int(count))):
            cur += step
            if cur < 0 or cur >= len(chunks):
                break
            c = chunks[cur]
            out.append(
                {
                    "path": meta["path"],
                    "category": meta["category"],
                    "chunk": c["text"],
                    "chunk_id": self._encode_chunk_id(fid, c["index"], chunk_chars, chunk_overlap),
                    "chunk_index": c["index"],
                    "chunk_total": len(chunks),
                }
            )

        return {"ok": True, "results": out, "source": meta["path"], "direction": direction}

