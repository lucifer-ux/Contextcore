from __future__ import annotations

from datetime import datetime, timezone

from core.indexing import IndexingEngine
from core.schema import Chunk, ContentType, Modality, NormalizedDocument, SourceType
from core.validators import compute_content_hash


def _doc(content: str = "hello", source_id: str = "C:/tmp/a.txt") -> NormalizedDocument:
    now = datetime.now(timezone.utc)
    return NormalizedDocument(
        source_type=SourceType.FILESYSTEM,
        source_id=source_id,
        content_hash=compute_content_hash(content),
        content=content,
        content_type=ContentType.DOCUMENT,
        modality=Modality.TEXT,
        language="en",
        author=None,
        created_at=now,
        updated_at=now,
        fetched_at=now,
        url=f"file:///{source_id}",
        space="C:/tmp",
        parent_id=None,
        thread_id=None,
        attachment_urls=[],
        metadata={},
        raw="{}",
    )


def _chunks(global_id: str) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"{global_id}:0",
            document_global_id=global_id,
            content_text="alpha",
            chunk_index=0,
            total_chunks=2,
            prev_chunk_id=None,
            next_chunk_id=f"{global_id}:1",
            position_start=0,
            position_end=5,
            position_display="Chunk 1 of 2",
            modality="text",
            language="en",
            content_summary=None,
            source_path="C:/tmp/a.txt",
            created_at=None,
            indexed_at=datetime.now(timezone.utc).isoformat(),
        ),
        Chunk(
            chunk_id=f"{global_id}:1",
            document_global_id=global_id,
            content_text="beta",
            chunk_index=1,
            total_chunks=2,
            prev_chunk_id=f"{global_id}:0",
            next_chunk_id=None,
            position_start=6,
            position_end=10,
            position_display="Chunk 2 of 2",
            modality="text",
            language="en",
            content_summary=None,
            source_path="C:/tmp/a.txt",
            created_at=None,
            indexed_at=datetime.now(timezone.utc).isoformat(),
        ),
    ]


def test_upsert_document_insert_unchanged_updated(tmp_path) -> None:
    db = tmp_path / "index.db"
    eng = IndexingEngine(str(db))
    try:
        doc = _doc("hello")
        assert eng.upsert_document(doc) == "inserted"
        assert eng.upsert_document(doc) == "unchanged"

        updated = _doc("hello2")
        assert eng.upsert_document(updated) == "updated"
    finally:
        eng.close()


def test_write_chunks_inserts_rows_in_all_tables(tmp_path) -> None:
    db = tmp_path / "index.db"
    eng = IndexingEngine(str(db))
    try:
        doc = _doc("hello")
        eng.upsert_document(doc)
        chunks = _chunks(doc.global_id())
        embeddings = {c.chunk_id: [0.01] * 512 for c in chunks}
        written = eng.write_chunks(chunks, embeddings=embeddings)
        assert written == 2

        c_count = eng.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        f_count = eng.conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        v_count = eng.conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0]
        assert c_count == 2
        assert f_count == 2
        assert v_count == 2
    finally:
        eng.close()


def test_delete_document_removes_rows(tmp_path) -> None:
    db = tmp_path / "index.db"
    eng = IndexingEngine(str(db))
    try:
        doc = _doc("hello")
        eng.upsert_document(doc)
        chunks = _chunks(doc.global_id())
        eng.write_chunks(chunks, embeddings={c.chunk_id: [0.02] * 512 for c in chunks})

        deleted = eng.delete_document(doc.global_id())
        assert deleted == 2
        assert eng.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert eng.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert eng.conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0
        assert eng.conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0] == 0
    finally:
        eng.close()


def test_get_neighbors_traversal(tmp_path) -> None:
    db = tmp_path / "index.db"
    eng = IndexingEngine(str(db))
    try:
        doc = _doc("hello")
        eng.upsert_document(doc)
        chunks = _chunks(doc.global_id())
        eng.write_chunks(chunks)

        nxt = eng.get_neighbors(chunks[0].chunk_id, direction="next", steps=1)
        assert len(nxt) == 1
        assert nxt[0]["chunk_id"] == chunks[1].chunk_id

        prev = eng.get_neighbors(chunks[1].chunk_id, direction="prev", steps=1)
        assert len(prev) == 1
        assert prev[0]["chunk_id"] == chunks[0].chunk_id
    finally:
        eng.close()


def test_write_then_delete_leaves_clean_db(tmp_path) -> None:
    db = tmp_path / "index.db"
    eng = IndexingEngine(str(db))
    try:
        doc = _doc("hello")
        eng.upsert_document(doc)
        eng.write_chunks(_chunks(doc.global_id()))
        eng.delete_document(doc.global_id())

        assert eng.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert eng.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    finally:
        eng.close()
