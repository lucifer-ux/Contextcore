"""
test_all.py - Pytest-compatible tests covering config import, path resolution,
dedup logic, hardcoded path checks, sqlite-vec availability, video MMR,
video transcript, video describe, video atomic writes, video topk,
watchdog, SDK imports, MCP fetch, MCP video shape, and requirements.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfig:
    def test_config_import(self):
        from config import (
            get_video_directories,
            get_audio_directories,
            get_image_directory,
            get_organized_root,
            get_dedup_threshold,
        )

    def test_config_returns_path_objects(self):
        from config import get_video_directories, get_image_directory

        vids = get_video_directories()
        assert isinstance(vids, list) and all(isinstance(p, Path) for p in vids)
        img = get_image_directory()
        assert isinstance(img, Path)

    def test_dedup_threshold_defaults(self):
        from config import get_dedup_threshold

        t = get_dedup_threshold()
        assert t == 0.85


class TestHardcodedPaths:
    def test_no_hardcoded_unimain(self):
        c = Path("unimain.py").read_text(encoding="utf-8")
        assert "/mnt/storage/organized_files/video" not in c
        assert "/mnt/storage/organized_files/audio" not in c

    def test_no_hardcoded_worker(self):
        c = Path("audio_search_implementation_v2/worker.py").read_text(encoding="utf-8")
        assert "/mnt/storage/organized_files" not in c


class TestDependencies:
    def test_sqlite_vec_importable(self):
        import sqlite_vec

    def test_watchdog_importable(self):
        import watchdog


class TestVideoIndex:
    def test_video_mmr_exists(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "mmr_is_unique" in c
        assert "selected_vecs" in c

    def test_video_no_annoy(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "AnnoyIndex" not in c
        code_lines = [l for l in c.splitlines() if l.strip() and not l.strip().startswith("#")]
        code_only = "\n".join(code_lines)
        assert ".npy" not in code_only
        assert "frame_vectors" in c

    def test_video_transcript(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "transcribe" in c.lower()
        assert "video_transcript" in c

    def test_video_describe(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "_describe_frame" in c
        assert "description" in c

    def test_video_atomic(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "conn.rollback()" in c
        assert "DELETE FROM frames WHERE video_id" in c

    def test_video_topk_default(self):
        c = Path("video_search_implementation_v2/video_index.py").read_text(encoding="utf-8")
        assert "top_k: int = 5" in c


class TestWatcher:
    def test_watcher_exists(self):
        assert Path("video_search_implementation_v2/watcher.py").exists()
        c = Path("video_search_implementation_v2/watcher.py").read_text(encoding="utf-8")
        assert "start_video_watcher" in c
        assert "stop_video_watcher" in c


class TestSDK:
    def test_sdk_core_module(self):
        assert Path("core/__init__.py").exists()
        assert Path("core/sdk.py").exists()
        c = Path("core/sdk.py").read_text(encoding="utf-8")
        for m in [
            "class ContextCore",
            "def embed_text",
            "def search(",
            "def index_directory",
            "def start_watcher",
        ]:
            assert m in c, f"Missing: {m}"


class TestMCP:
    def test_mcp_fetch(self):
        c = Path("mcp_server.py").read_text(encoding="utf-8")
        assert "def fetch_content" in c
        assert "_fetch_video_content" in c

    def test_mcp_video_shape(self):
        c = Path("mcp_server.py").read_text(encoding="utf-8")
        assert '"description"' in c
        assert '"best_timestamp"' in c

    def test_mcp_image_shape_ocr(self):
        c = Path("mcp_server.py").read_text(encoding="utf-8")
        assert '"match_type"' in c
        assert '"ocr_text"' in c
        assert '"ocr_snippet"' in c


class TestImageSearch:
    def test_annoy_sqlite_wired(self):
        c = Path("unimain.py").read_text(encoding="utf-8")
        assert "image_search_implementation_v2.search" in c
        assert "annoy_sqlite_ocr" in c
        assert 'semantic_backend": "annoy_sqlite"' in c

    def test_image_status_annoy_fields(self):
        c = Path("unimain.py").read_text(encoding="utf-8")
        assert '"indexed_images_with_ocr"' in c
        assert '"ocr_coverage"' in c
        assert '"engine": "annoy_sqlite_ocr"' in c
        assert '"annoy_needs_rebuild"' in c

    def test_image_result_score_fields(self):
        c = Path("image_search_implementation_v2/search.py").read_text(encoding="utf-8")
        assert '"semantic_score"' in c
        assert '"ocr_score"' in c
        assert '"filename_score"' in c
        assert '"final_score"' in c


class TestRequirements:
    def test_requirements_has_deps(self):
        c = Path("requirements.txt").read_text(encoding="utf-8")
        assert "sqlite-vec" in c
        assert "watchdog" in c
