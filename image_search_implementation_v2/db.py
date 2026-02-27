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

def init_db():
    conn = get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                filename TEXT,
                mtime REAL,
                has_ocr INTEGER DEFAULT 0
            )
        """)
        # FTS5 virtual table for filename + ocr_text
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
                filename, ocr_text, content='images', content_rowid='id', tokenize='porter'
            )
        """)
    conn.close()

def upsert_image(path: str, filename: str, mtime: float, ocr_text: str | None):
    conn = get_conn()
    with conn:
        cur = conn.execute("SELECT id, mtime FROM images WHERE path = ?", (path,))
        row = cur.fetchone()
        if row:
            if row["mtime"] >= mtime:
                return False, row["id"]  # unchanged
            image_id = row["id"]
            conn.execute("UPDATE images SET filename = ?, mtime = ?, has_ocr = ? WHERE id = ?",
                         (filename, mtime, 1 if ocr_text else 0, image_id))
            conn.execute("DELETE FROM images_fts WHERE rowid = ?", (image_id,))
        else:
            cur2 = conn.execute("INSERT INTO images (path, filename, mtime, has_ocr) VALUES (?, ?, ?, ?)",
                                (path, filename, mtime, 1 if ocr_text else 0))
            image_id = cur2.lastrowid
        # populate FTS
        conn.execute("INSERT INTO images_fts(rowid, filename, ocr_text) VALUES (?, ?, ?)",
                     (image_id, filename, ocr_text or ""))
    conn.close()
    return True, image_id

def get_metadata_by_ids(ids):
    if not ids:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"SELECT id, path, filename, mtime FROM images WHERE id IN ({placeholders})", ids)
    rows = cur.fetchall()
    conn.close()
    return {r["id"]: dict(r) for r in rows}

def query_fts(match_query: str, limit: int = 50):
    conn = get_conn()
    cur = conn.execute(
        "SELECT rowid as id, bm25(images_fts) as score FROM images_fts WHERE images_fts MATCH ? ORDER BY score LIMIT ?",
        (match_query, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def all_filenames():
    conn = get_conn()
    cur = conn.execute("SELECT id, filename, path FROM images")
    rows = cur.fetchall()
    conn.close()
    return rows
