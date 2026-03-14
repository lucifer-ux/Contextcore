# core/__init__.py
#
# ContextCore SDK — Layer 1 (core library)
# ─────────────────────────────────────────
# Clean, stateless public API for embedding, indexing, and search.
# No FastAPI, no MCP — just Python functions that SDK consumers call directly.
#
# Usage:
#   from core import ContextCore
#   ctx = ContextCore(config_path="contextcore.yaml")
#   ctx.index_directory("/path/to/files")
#   results = ctx.search("meeting notes", modality="all", top_k=5)

from core.sdk import ContextCore

__all__ = ["ContextCore"]
