# core/sdk.py
#
# ContextCore SDK — the main entry point for SDK consumers.
# This is a stateless, config-driven Python class that wraps all
# embedding, indexing, and search capabilities.
#
# Designed to be used directly without starting a server:
#   ctx = ContextCore(config_path="contextcore.yaml")
#   ctx.index_directory("/my/files")
#   results = ctx.search("quarterly report", modality="text", top_k=5)

import sys
from pathlib import Path
from typing import Any, Optional

# Ensure parent dir is on Python path for sibling imports
_SDK_ROOT = Path(__file__).resolve().parent.parent
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))


class ContextCore:
    """
    ContextCore SDK — plug-and-play search and indexing for local files.

    Three integration modes share this core:
      1. SDK (this class)    — direct Python usage
      2. System App          — FastAPI endpoints in unimain.py
      3. MCP                 — tool integration in mcp_server.py

    All configuration is read from contextcore.yaml with env var fallbacks.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the SDK. Optionally pass a path to contextcore.yaml.
        If not provided, the default search order is used (project root → CWD).
        """
        if config_path:
            import config as cfg_module
            # Override the config file location
            import os
            os.environ.setdefault("CONTEXTCORE_CONFIG", config_path)
            cfg_module.reload_config()

        # Lazily loaded modules — we don't import heavy ML libs at init time
        self._clip_loaded = False

    # ── Embedding ─────────────────────────────────────────────

    def embed_text(self, text: str):
        """Embed a text string using CLIP. Returns a numpy float32 vector."""
        from unimain import embed_text_with_clip
        return embed_text_with_clip(text)

    def embed_image(self, image_path: str):
        """Embed an image file using CLIP. Returns a numpy float32 vector."""
        from unimain import embed_image_file
        return embed_image_file(Path(image_path))

    # ── Indexing ──────────────────────────────────────────────

    def index_text(self, directory: Optional[str] = None) -> dict:
        """
        Index text files. If no directory given, uses the configured
        organized_root from contextcore.yaml.
        """
        from unimain import scan_text_index
        return scan_text_index()

    def index_images(self, directory: Optional[str] = None) -> dict:
        """
        Index image files. If no directory given, uses the configured
        image directory from contextcore.yaml.
        """
        from unimain import scan_image_index
        return {"status": "ok", "result": scan_image_index(directory=directory)}

    def index_videos(
        self,
        directory: Optional[str] = None,
        dedup_threshold: float = 0.85,
        max_frames: int = 80,
    ) -> dict:
        """
        Index video files. Extracts frames, deduplicates with MMR,
        generates descriptions, and transcribes audio.

        Args:
            directory: Path to video directory. Uses config if None.
            dedup_threshold: Cosine similarity threshold for frame dedup (0.0-1.0).
            max_frames: Maximum frames to extract per video.
        """
        from video_search_implementation_v2.video_index import scan_video_index
        from config import get_video_directories

        dirs = [Path(directory)] if directory else get_video_directories()
        total_new = 0
        for d in dirs:
            if d.is_dir():
                result = scan_video_index(
                    d,
                    max_frames_per_video=max_frames,
                    dedup_threshold=dedup_threshold,
                )
                total_new += result.get("new_vectors", 0)
        return {"status": "ok", "new_vectors": total_new}

    def index_audio(self, directory: Optional[str] = None) -> dict:
        """Index audio files using Whisper transcription."""
        from audio_search_implementation_v2.audio_index import scan_audio_index
        from config import get_audio_directories

        dirs = [Path(directory)] if directory else get_audio_directories()
        total_new = 0
        for d in dirs:
            if d.is_dir():
                result = scan_audio_index(d)
                total_new += result.get("new_audio_indexed", 0)
        return {"status": "ok", "new_audio_indexed": total_new}

    def index_code(self, directory: str, force: bool = False) -> dict:
        """
        Index a code repository. Extracts symbols, dependencies, and structure.
        """
        from unimain import scan_code_index_wrapper
        return scan_code_index_wrapper(directory)

    def index_directory(
        self,
        directory: str,
        text: bool = True,
        images: bool = True,
        videos: bool = True,
        audio: bool = True,
        code: bool = False,
    ) -> dict:
        """
        Index all content types in a directory. This is the primary SDK entry point.

        Args:
            directory: Path to the directory to index.
            text: Index text/document files.
            images: Index image files (CLIP embeddings).
            videos: Index video files (frames + transcripts).
            audio: Index audio files (Whisper transcription).
            code: Index code files (symbols + dependencies).
        """
        results = {}
        if text:
            results["text"] = self.index_text(directory)
        if images:
            results["images"] = self.index_images(directory)
        if videos:
            results["videos"] = self.index_videos(directory)
        if audio:
            results["audio"] = self.index_audio(directory)
        if code:
            results["code"] = self.index_code(directory)
        return results

    # ── Search ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        modality: str = "all",
        top_k: int = 5,
    ) -> dict:
        """
        Search across all indexed content.

        Args:
            query: Natural language search query.
            modality: One of "all", "text", "image", "video", "audio".
            top_k: Number of results to return.

        Returns:
            Dict with modality-keyed results.
        """
        results: dict[str, Any] = {}

        if modality in ("all", "text", "audio"):
            from unimain import run_text_search
            text_results = run_text_search(query, top_k=top_k)
            results["text"] = text_results

        if modality in ("all", "image"):
            from unimain import run_image_search
            image_results = run_image_search(query, top_k=top_k)
            results["image"] = image_results

        if modality in ("all", "video"):
            from unimain import run_video_search
            video_results = run_video_search(query, top_k=top_k)
            results["video"] = video_results

        return results

    def search_text(self, query: str, top_k: int = 10) -> dict:
        """Search text/document content only."""
        from unimain import run_text_search
        return run_text_search(query, top_k=top_k)

    def search_images(self, query: str, top_k: int = 10) -> dict:
        """Search images using CLIP text-to-image similarity."""
        from unimain import run_image_search
        return run_image_search(query, top_k=top_k)

    def search_videos(self, query: str, top_k: int = 5) -> dict:
        """Search videos using frame embeddings + transcript FTS."""
        from unimain import run_video_search
        return run_video_search(query, top_k=top_k)

    # ── Watcher ───────────────────────────────────────────────

    def start_watcher(self):
        """Start background filesystem watcher for video directories."""
        from video_search_implementation_v2.watcher import start_video_watcher
        start_video_watcher()

    def stop_watcher(self):
        """Stop the filesystem watcher."""
        from video_search_implementation_v2.watcher import stop_video_watcher
        stop_video_watcher()

    # ── Config ────────────────────────────────────────────────

    @staticmethod
    def reload_config():
        """Force-reload contextcore.yaml."""
        from config import reload_config
        return reload_config()
