# image_search_implementation_v2/db.py
import sqlite3
from pathlib import Path

from .config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_db():
    conn = get_conn()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                filename TEXT,
                mtime REAL,
                has_ocr INTEGER DEFAULT 0,
                ocr_text TEXT DEFAULT '',
                annoy_id INTEGER,
                embedding_path TEXT,
                embedding_hash TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
                filename, ocr_text, content='images', content_rowid='id', tokenize='porter'
            )
            """
        )
        _ensure_column(conn, "images", "annoy_id", "INTEGER")
        _ensure_column(conn, "images", "embedding_path", "TEXT")
        _ensure_column(conn, "images", "embedding_hash", "TEXT")
        _ensure_column(conn, "images", "ocr_text", "TEXT DEFAULT ''")
        try:
            conn.execute("SELECT ocr_text FROM images_fts LIMIT 1").fetchall()
        except Exception:
            conn.execute("DROP TABLE IF EXISTS images_fts")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
                    filename, ocr_text, content='images', content_rowid='id', tokenize='porter'
                )
                """
            )
            rows = conn.execute("SELECT id, filename, ocr_text FROM images").fetchall()
            for r in rows:
                conn.execute(
                    "INSERT INTO images_fts(rowid, filename, ocr_text) VALUES (?, ?, ?)",
                    (int(r["id"]), r["filename"] or "", r["ocr_text"] or ""),
                )
    conn.close()


def upsert_image(path: str, filename: str, mtime: float, ocr_text: str | None):
    conn = get_conn()
    with conn:
        cur = conn.execute("SELECT id, mtime FROM images WHERE path = ?", (path,))
        row = cur.fetchone()
        if row:
            image_id = int(row["id"])
            if float(row["mtime"]) >= float(mtime):
                return False, image_id
            conn.execute(
                """
                UPDATE images
                SET filename = ?, mtime = ?, has_ocr = ?, ocr_text = ?, embedding_path = NULL, embedding_hash = NULL
                WHERE id = ?
                """,
                (filename, mtime, 1 if ocr_text else 0, ocr_text or "", image_id),
            )
            conn.execute("DELETE FROM images_fts WHERE rowid = ?", (image_id,))
        else:
            cur2 = conn.execute(
                """
                INSERT INTO images (path, filename, mtime, has_ocr, ocr_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (path, filename, mtime, 1 if ocr_text else 0, ocr_text or ""),
            )
            image_id = int(cur2.lastrowid)
        conn.execute(
            "INSERT INTO images_fts(rowid, filename, ocr_text) VALUES (?, ?, ?)",
            (image_id, filename, ocr_text or ""),
        )
    conn.close()
    return True, image_id


def needs_embedding(image_id: int) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT embedding_path FROM images WHERE id = ?",
        (int(image_id),),
    ).fetchone()
    conn.close()
    if not row:
        return True
    emb_path = (row["embedding_path"] or "").strip()
    return not emb_path


def allocate_annoy_id(image_id: int) -> int:
    conn = get_conn()
    with conn:
        row = conn.execute("SELECT annoy_id FROM images WHERE id = ?", (int(image_id),)).fetchone()
        if not row:
            raise ValueError(f"image id not found: {image_id}")
        if row["annoy_id"] is not None:
            return int(row["annoy_id"])
        next_row = conn.execute("SELECT MAX(annoy_id) as mx FROM images").fetchone()
        next_annoy_id = int(next_row["mx"] or 0) + 1
        conn.execute("UPDATE images SET annoy_id = ? WHERE id = ?", (next_annoy_id, int(image_id)))
    conn.close()
    return next_annoy_id


def update_embedding_meta(image_id: int, annoy_id: int, embedding_path: str, embedding_hash: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            """
            UPDATE images
            SET annoy_id = ?, embedding_path = ?, embedding_hash = ?
            WHERE id = ?
            """,
            (int(annoy_id), str(embedding_path), str(embedding_hash), int(image_id)),
        )
    conn.close()


def get_metadata_by_ids(ids):
    if not ids:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"""
        SELECT
            i.id,
            i.path,
            i.filename,
            i.mtime,
            i.has_ocr,
            i.annoy_id,
            i.embedding_path,
            i.embedding_hash,
            COALESCE(i.ocr_text, '') AS ocr_text
        FROM images i
        WHERE i.id IN ({placeholders})
        """,
        ids,
    )
    rows = cur.fetchall()
    conn.close()
    return {int(r["id"]): dict(r) for r in rows}


def get_metadata_by_annoy_ids(annoy_ids):
    if not annoy_ids:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" for _ in annoy_ids)
    cur = conn.execute(
        f"""
        SELECT
            i.id,
            i.path,
            i.filename,
            i.mtime,
            i.has_ocr,
            i.annoy_id,
            i.embedding_path,
            i.embedding_hash,
            COALESCE(i.ocr_text, '') AS ocr_text
        FROM images i
        WHERE i.annoy_id IN ({placeholders})
        """,
        [int(a) for a in annoy_ids],
    )
    rows = cur.fetchall()
    conn.close()
    out = {}
    for r in rows:
        out[int(r["annoy_id"])] = dict(r)
    return out


def iter_annoy_vectors():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT annoy_id, embedding_path
        FROM images
        WHERE annoy_id IS NOT NULL
          AND embedding_path IS NOT NULL
          AND LENGTH(TRIM(embedding_path)) > 0
        ORDER BY annoy_id ASC
        """
    ).fetchall()
    conn.close()
    return rows


def count_images() -> int:
    conn = get_conn()
    n = int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0])
    conn.close()
    return n


def count_ocr_images() -> int:
    conn = get_conn()
    n = int(conn.execute("SELECT COUNT(*) FROM images WHERE has_ocr = 1").fetchone()[0])
    conn.close()
    return n


def count_vector_ready_images() -> int:
    conn = get_conn()
    n = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM images
            WHERE annoy_id IS NOT NULL
              AND embedding_path IS NOT NULL
              AND LENGTH(TRIM(embedding_path)) > 0
            """
        ).fetchone()[0]
    )
    conn.close()
    return n


def query_fts(match_query: str, limit: int = 50):
    conn = get_conn()
    cur = conn.execute(
        """
        SELECT
            rowid as id,
            bm25(images_fts) as score
        FROM images_fts
        WHERE images_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (match_query, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def all_filenames():
    conn = get_conn()
    rows = conn.execute("SELECT id, filename, path FROM images").fetchall()
    conn.close()
    return rows
