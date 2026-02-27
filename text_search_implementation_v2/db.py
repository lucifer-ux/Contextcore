# text_search_implementation_v2/db.py
import sqlite3
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "storage"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "text_search_implementation_v2.db"

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    # pragma for performance / concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    conn = get_conn()
    with conn:
        # metadata table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                filename TEXT,
                category TEXT,
                mtime REAL
            )
            """
        )
        # FTS5 virtual table for content + filename
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                filename, content, content='files', content_rowid='id', tokenize='porter'
            );
            """
        )
    conn.close()

# helper to upsert file metadata and fts content
def upsert_file(path: str, filename: str, category: str, mtime: float, content: str):
    conn = get_conn()
    with conn:
        # upsert metadata
        cur = conn.execute(
            "SELECT id, mtime FROM files WHERE path = ?",
            (path,)
        )
        row = cur.fetchone()
        if row:
            if row["mtime"] >= mtime:
                return False  # unchanged
            file_id = row["id"]
            conn.execute(
                "UPDATE files SET filename = ?, category = ?, mtime = ? WHERE id = ?",
                (filename, category, mtime, file_id),
            )
            conn.execute(
                "DELETE FROM files_fts WHERE rowid = ?",
                (file_id,)
            )
        else:
            cur = conn.execute(
                "INSERT INTO files (path, filename, category, mtime) VALUES (?, ?, ?, ?)",
                (path, filename, category, mtime)
            )
            file_id = cur.lastrowid

        # insert into fts
        conn.execute(
            "INSERT INTO files_fts(rowid, filename, content) VALUES (?, ?, ?)",
            (file_id, filename, content)
        )
    conn.close()
    return True

def query_fts(match_query: str, limit: int = 50):
    conn = get_conn()
    cur = conn.execute(
        "SELECT rowid as id, bm25(files_fts) as score FROM files_fts WHERE files_fts MATCH ? ORDER BY score LIMIT ?",
        (match_query, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def get_file_metadata_by_ids(ids):
    if not ids:
        return []
    conn = get_conn()
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"SELECT id, path, filename, category FROM files WHERE id IN ({placeholders})", ids)
    rows = cur.fetchall()
    conn.close()
    return {r["id"]: dict(r) for r in rows}

def get_file_mtime(path: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT mtime FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
