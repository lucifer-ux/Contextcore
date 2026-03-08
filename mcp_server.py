"""
MCP adapter for ContextCore unified search backend.

Three tools only:
  1. search         - find relevant content across all indexed sources
  2. index_content  - trigger background indexing when content seems stale
  3. list_sources   - discover what connectors and paths are indexed
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

SERVER_NAME = "contextcore-unified"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 120

BACKEND_BASE_URL = os.getenv("CONTEXTCORE_API_BASE_URL", DEFAULT_BACKEND_URL).rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("CONTEXTCORE_MCP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
PROJECT_ROOT = Path(__file__).resolve().parent
RETRIEVAL_BUDGET_MAX_CALLS = int(os.getenv("CONTEXTCORE_RETRIEVAL_BUDGET", "4"))

mcp = FastMCP(SERVER_NAME, json_response=True)
_BUDGET_LOCK = threading.Lock()
_SESSION_BUDGETS: dict[str, int] = {}
_SESSION_LAST_QUERY: dict[str, str] = {}
_FEEDBACK_DB = PROJECT_ROOT / "storage" / "mcp_feedback.db"

LOCAL_FILESYSTEM_TOOLS = {
    "claude-code",
    "cline",
    "aider",
    "opencode",
    "goose",
    "continue",
    "cursor",
    "windsurf",
    "codex",
}
REMOTE_ONLY_TOOLS = {
    "claude-desktop",
    "claude.ai",
    "chatgpt-web",
    "gemini-web",
    "perplexity",
    "browser-chat",
}


def _request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    url = f"{BACKEND_BASE_URL}{path}"
    try:
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            timeout=REQUEST_TIMEOUT if timeout is None else timeout,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "backend_unreachable",
            "message": str(exc),
            "backend_url": BACKEND_BASE_URL,
            "path": path,
        }

    if not resp.ok:
        try:
            detail: Any = resp.json()
        except ValueError:
            detail = resp.text
        return {
            "ok": False,
            "error": "backend_error",
            "status_code": resp.status_code,
            "detail": detail,
            "path": path,
        }

    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    return {"ok": True, "data": payload}


def _safe_sql_count(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> int:
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        return int(row[0] if row and row[0] is not None else 0)
    except Exception:
        return 0


def _init_feedback_db() -> None:
    _FEEDBACK_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_FEEDBACK_DB))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refine_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            session_id TEXT,
            original_query TEXT,
            reason TEXT,
            refined_query TEXT,
            exclude_sources TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _log_refine_feedback(
    session_id: str,
    original_query: str,
    reason: str,
    refined_query: str,
    exclude_sources: list[str] | None,
) -> None:
    try:
        _init_feedback_db()
        conn = sqlite3.connect(str(_FEEDBACK_DB))
        conn.execute(
            """
            INSERT INTO refine_feedback(session_id, original_query, reason, refined_query, exclude_sources)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, original_query, reason, refined_query, ",".join(exclude_sources or [])),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _consume_budget(session_id: str, reset: bool = False) -> dict[str, Any]:
    sid = session_id.strip() or "default"
    with _BUDGET_LOCK:
        if reset or sid not in _SESSION_BUDGETS:
            _SESSION_BUDGETS[sid] = RETRIEVAL_BUDGET_MAX_CALLS
        if _SESSION_BUDGETS[sid] <= 0:
            return {
                "ok": False,
                "error": "retrieval_budget_exhausted",
                "session_id": sid,
                "budget_remaining": 0,
                "budget_max": RETRIEVAL_BUDGET_MAX_CALLS,
            }
        _SESSION_BUDGETS[sid] -= 1
        return {
            "ok": True,
            "session_id": sid,
            "budget_remaining": _SESSION_BUDGETS[sid],
            "budget_max": RETRIEVAL_BUDGET_MAX_CALLS,
        }


def _reveal_file_in_explorer(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": "file_not_found", "path": str(path)}

    try:
        if sys.platform.startswith("win"):
            target = str(path.resolve())
            # Explorer select mode. Quoted form is more reliable for spaces/special chars.
            try:
                subprocess.Popen(["explorer.exe", f'/select,"{target}"'])
            except Exception:
                # Fallback form used by some shells/setups.
                subprocess.Popen(["explorer.exe", f"/select,{target}"])
            return {
                "ok": True,
                "opened": "explorer",
                "path": target,
                "note": "Requested highlighted selection in Explorer",
            }
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return {"ok": True, "opened": "finder", "path": str(path)}

        # Linux fallback: open containing directory.
        subprocess.Popen(["xdg-open", str(path.parent)])
        return {"ok": True, "opened": "file-manager", "path": str(path), "note": "Opened parent directory"}
    except Exception as exc:
        return {"ok": False, "error": "reveal_failed", "path": str(path), "message": str(exc)}


def _normalize_tool_name(tool: str) -> str:
    return (tool or "").strip().lower()


def _should_auto_reset_budget(session_id: str, query: str) -> bool:
    sid = session_id.strip() or "default"
    normalized = " ".join((query or "").strip().lower().split())
    with _BUDGET_LOCK:
        prev = _SESSION_LAST_QUERY.get(sid)
        _SESSION_LAST_QUERY[sid] = normalized
    return prev != normalized


def _load_source_config() -> dict[str, Any]:
    text_base = "/mnt/storage/organized_files"
    text_folders = ["docs", "spreadsheets", "code"]
    image_folder = "images"

    try:
        from text_search_implementation_v2.config import BASE_DIR as tb, TEXT_FOLDERS

        text_base = str(tb)
        text_folders = sorted(list(TEXT_FOLDERS))
    except Exception:
        pass

    try:
        from image_search_implementation_v2.config import BASE_DIR as ib, IMAGE_FOLDER

        if text_base == "/mnt/storage/organized_files":
            text_base = str(ib)
        image_folder = str(IMAGE_FOLDER)
    except Exception:
        pass

    return {
        "base_dir": text_base,
        "text_folders": text_folders,
        "image_folder": image_folder,
        "video_folder": "video",
        "audio_folder": "audio",
    }


@mcp.tool()
def search(
    query: str,
    top_k: int = 5,
    modality: str = "all",
    session_id: str = "default",
    reset_budget: bool = False,
    include_metadata: bool = False,
) -> dict[str, Any]:
    """
    Search the user's indexed content - documents, messages, images,
    audio transcripts, and videos - and return the most relevant results
    with exact source paths.

    WHEN TO CALL:
    Call this tool first whenever the user asks about anything that might
    exist in their files, messages, or stored content. Always call this
    before attempting to answer from memory alone.

    PARAMETERS:
    - query: the user's question or topic in natural language. Do not
      rewrite or simplify the query - pass it as the user said it.
    - top_k: number of results to return. Use 5 (default) for most
      questions. Use 10 if the user wants a broad overview or asks to
      compare multiple things. Never exceed 15.
    - modality: filter by content type. Use "all" (default) unless the
      user specifically asks about images ("image"), videos ("video"),
      audio recordings ("audio"), or documents ("text").

    AFTER CALLING:
    Use the returned content and source paths directly in your response.
    Cite the source field so the user knows exactly where each piece of
    information came from. Do not call run_llm or any other tool after
    this - answer from the results directly.

    WHEN RESULTS ARE EMPTY:
    If results are empty or scores are all below 0.1, tell the user their
    content may not be indexed yet and suggest they run index_content.
    Do not guess or hallucinate an answer if search returns nothing useful.
    """
    normalized_modality = modality.strip().lower()
    if normalized_modality not in {"all", "text", "image", "video", "audio"}:
        return {
            "ok": False,
            "error": "invalid_modality",
            "message": "modality must be one of: all, text, image, video, audio",
        }

    auto_reset = _should_auto_reset_budget(session_id=session_id, query=query)
    budget = _consume_budget(session_id=session_id, reset=(reset_budget or auto_reset))
    if not budget.get("ok"):
        return budget

    bounded_top_k = max(1, min(int(top_k), 15))
    upstream_top_k = max(20, bounded_top_k) if normalized_modality == "all" else bounded_top_k
    upstream = _request_json(
        "GET",
        "/search",
        params={
            "query": query,
            "top_k": upstream_top_k,
            "modality": normalized_modality,
            "text_include_metadata": include_metadata,
        },
        timeout=60,
    )
    if not upstream.get("ok"):
        return upstream

    payload = upstream["data"]
    text_results = payload.get("text", {}).get("results", []) if isinstance(payload.get("text"), dict) else []
    image_results = payload.get("image", {}).get("results", []) if isinstance(payload.get("image"), dict) else []
    video_results = payload.get("video", {}).get("results", []) if isinstance(payload.get("video"), dict) else []

    def _shape_text(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "modality": "audio" if str(r.get("category", "")).lower() == "audio" else "text",
                    "source": r.get("path"),
                    "filename": r.get("filename"),
                    "score": float(r.get("score", 0.0)),
                    "category": r.get("category"),
                    "chunk": r.get("chunk"),
                    "chunk_id": r.get("chunk_id"),
                    "chunk_index": r.get("chunk_index"),
                    "chunk_total": r.get("chunk_total"),
                }
            )
        return out

    def _shape_images(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "modality": "image",
                    "source": r.get("path"),
                    "filename": r.get("filename"),
                    "score": float(r.get("score", 0.0)),
                }
            )
        return out

    def _shape_videos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "modality": "video",
                    "source": r.get("video_path"),
                    "score": float(r.get("score", 0.0)),
                }
            )
        return out

    text_shaped = _shape_text(text_results)
    image_shaped = _shape_images(image_results)
    video_shaped = _shape_videos(video_results)

    if normalized_modality == "all":
        merged = text_shaped + image_shaped + video_shaped
    elif normalized_modality == "text":
        merged = [r for r in text_shaped if r["modality"] == "text"]
    elif normalized_modality == "audio":
        merged = [r for r in text_shaped if r["modality"] == "audio"]
    elif normalized_modality == "image":
        merged = image_shaped
    else:
        merged = video_shaped

    merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    merged = merged[:bounded_top_k]

    return {
        "ok": True,
        "query": query,
        "modality": normalized_modality,
        "top_k": bounded_top_k,
        "session_id": budget.get("session_id"),
        "budget_remaining": budget.get("budget_remaining"),
        "budget_max": budget.get("budget_max"),
        "result_count": len(merged),
        "results": merged,
        "empty_or_low_confidence": (not merged) or all(float(r.get("score", 0.0)) < 0.1 for r in merged),
    }


@mcp.tool()
def list_files(
    directory: str,
    recursive: bool = True,
    limit: int = 100,
    pattern: str = "*",
) -> dict[str, Any]:
    """
    List files from a local directory (served by backend /files/list) and include fetchable URLs.
    """
    bounded_limit = max(1, min(int(limit), 1000))
    upstream = _request_json(
        "GET",
        "/files/list",
        params={
            "directory": directory,
            "recursive": recursive,
            "limit": bounded_limit,
            "pattern": pattern,
        },
        timeout=30,
    )
    if not upstream.get("ok"):
        return upstream

    data = upstream["data"]
    rows = data.get("files", []) if isinstance(data, dict) else []
    out = []
    for r in rows:
        p = r.get("path")
        out.append(
            {
                "path": p,
                "filename": r.get("filename"),
                "size_bytes": r.get("size_bytes"),
                "mime_type": r.get("mime_type"),
                "mtime": r.get("mtime"),
            }
        )

    return {
        "ok": True,
        "directory": data.get("directory"),
        "count": len(out),
        "files": out,
    }


@mcp.tool()
def reveal_file(path: str) -> dict[str, Any]:
    """
    Open the OS file manager with the target file selected so user can drag/drop it into chat.
    """
    return _reveal_file_in_explorer(Path(path).expanduser().resolve())


@mcp.tool()
def filesystem_access_profile(tool: str) -> dict[str, Any]:
    """
    Return filesystem access mode guidance for a client tool.
    """
    t = _normalize_tool_name(tool)
    if t in LOCAL_FILESYSTEM_TOOLS:
        return {
            "ok": True,
            "tool": t,
            "access_mode": "direct_local_filesystem",
            "can_read_absolute_paths": True,
            "recommended_flow": "return absolute path and let tool open/read directly",
        }
    if t in REMOTE_ONLY_TOOLS:
        return {
            "ok": True,
            "tool": t,
            "access_mode": "remote_no_local_filesystem",
            "can_read_absolute_paths": False,
            "recommended_flow": "reveal file in OS explorer and ask user to drag/drop upload",
        }
    return {
        "ok": True,
        "tool": t,
        "access_mode": "unknown",
        "can_read_absolute_paths": False,
        "recommended_flow": "assume remote unless verified; use reveal + drag/drop flow",
    }


@mcp.tool()
def prepare_file_for_tool(path: str, tool: str) -> dict[str, Any]:
    """
    Prepare a local file for a specific client tool:
    - local agents: return absolute path for direct read
    - remote/web tools: open explorer/finder selection for drag-drop flow
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"ok": False, "error": "file_not_found", "path": str(p)}

    profile = filesystem_access_profile(tool)
    if profile.get("can_read_absolute_paths"):
        return {
            "ok": True,
            "tool": profile.get("tool"),
            "access_mode": profile.get("access_mode"),
            "path": str(p),
            "next_step": "Tool can read this path directly.",
        }

    revealed = _reveal_file_in_explorer(p)
    return {
        "ok": bool(revealed.get("ok")),
        "tool": profile.get("tool"),
        "access_mode": profile.get("access_mode"),
        "path": str(p),
        "reveal": revealed,
        "next_step": "File manager opened. Ask user to drag/drop this file into chat.",
    }


@mcp.tool()
def refine_search(
    original_query: str,
    reason: str,
    refined_query: str,
    exclude_sources: list[str] | None = None,
    top_k: int = 5,
    modality: str = "text",
    session_id: str = "default",
    include_metadata: bool = False,
) -> dict[str, Any]:
    budget = _consume_budget(session_id=session_id, reset=False)
    if not budget.get("ok"):
        return budget

    _log_refine_feedback(
        session_id=session_id,
        original_query=original_query,
        reason=reason,
        refined_query=refined_query,
        exclude_sources=exclude_sources,
    )

    normalized_modality = modality.strip().lower()
    if normalized_modality not in {"all", "text", "image", "video", "audio"}:
        return {
            "ok": False,
            "error": "invalid_modality",
            "message": "modality must be one of: all, text, image, video, audio",
        }

    bounded_top_k = max(1, min(int(top_k), 15))
    params: dict[str, Any] = {
        "query": refined_query,
        "top_k": max(20, bounded_top_k) if normalized_modality == "all" else bounded_top_k,
        "modality": normalized_modality,
        "text_include_metadata": include_metadata,
    }
    if exclude_sources:
        params["exclude_sources"] = ",".join(str(s) for s in exclude_sources if str(s).strip())

    upstream = _request_json("GET", "/search", params=params, timeout=60)
    if not upstream.get("ok"):
        return upstream

    return {
        "ok": True,
        "original_query": original_query,
        "reason": reason,
        "query": refined_query,
        "session_id": budget.get("session_id"),
        "budget_remaining": budget.get("budget_remaining"),
        "budget_max": budget.get("budget_max"),
        "data": upstream["data"],
    }


@mcp.tool()
def get_neighbors(
    chunk_id: str,
    direction: str = "next",
    count: int = 1,
    session_id: str = "default",
) -> dict[str, Any]:
    budget = _consume_budget(session_id=session_id, reset=False)
    if not budget.get("ok"):
        return budget

    upstream = _request_json(
        "GET",
        "/search/text/neighbors",
        params={
            "chunk_id": chunk_id,
            "direction": direction,
            "count": max(1, min(int(count), 5)),
        },
        timeout=30,
    )
    if not upstream.get("ok"):
        return upstream

    return {
        "ok": True,
        "session_id": budget.get("session_id"),
        "budget_remaining": budget.get("budget_remaining"),
        "budget_max": budget.get("budget_max"),
        "data": upstream["data"],
    }


@mcp.tool()
def index_content(
    run_text: bool = True,
    run_image: bool = True,
    run_video: bool = True,
    run_audio: bool = True,
) -> dict[str, Any]:
    """
    Trigger a background scan to index new or updated files from all
    configured sources. Returns immediately - indexing runs in background.

    WHEN TO CALL:
    Only call this if:
    - The user explicitly says content is missing from search results
    - The user says "re-index", "refresh", or "scan my files"
    - search() returned empty results and the user confirms the content
      should exist

    Do NOT call this proactively before every search. Only call when
    the user has indicated something is out of date or missing.

    PARAMETERS:
    Set a modality to False only if the user specifically says to skip it.
    Default is to scan all modalities.

    AFTER CALLING:
    Tell the user indexing has started in the background and search
    results will improve within a few minutes for small collections,
    or longer for large ones. Do not wait for it to complete.
    """
    return _request_json(
        "POST",
        "/index/scan",
        params={
            "run_text": run_text,
            "run_image": run_image,
            "run_video": run_video,
            "run_audio": run_audio,
        },
        timeout=30,
    )


@mcp.tool()
def list_sources() -> dict[str, Any]:
    """
    Return what content sources are currently configured and indexed -
    folders being watched, connectors active, and a count of indexed
    items per modality.

    WHEN TO CALL:
    Call this only if:
    - The user asks "what do you have access to" or "what's indexed"
    - The user asks "where are you searching" or "what sources do you use"
    - You need to tell the user why search returned nothing (to show
      what is and isn't connected)

    Do NOT call this before every search. Only call on explicit user
    request about available sources.

    AFTER CALLING:
    Summarize the sources in plain language. Tell the user what folders
    or services are connected and roughly how much content is indexed.
    """
    cfg = _load_source_config()
    base_dir = cfg["base_dir"]

    text_db = PROJECT_ROOT / "text_search_implementation_v2" / "storage" / "text_search_implementation_v2.db"
    image_db = PROJECT_ROOT / "image_search_implementation_v2" / "storage" / "images_v2.db"
    video_db = PROJECT_ROOT / "video_search_implementation_v2" / "storage" / "videos_meta.db"

    text_total = _safe_sql_count(text_db, "SELECT COUNT(*) FROM files")
    audio_total = _safe_sql_count(text_db, "SELECT COUNT(*) FROM files WHERE LOWER(category) = 'audio'")
    doc_text_total = max(0, text_total - audio_total)
    image_total = _safe_sql_count(image_db, "SELECT COUNT(*) FROM images")
    video_total = _safe_sql_count(video_db, "SELECT COUNT(*) FROM videos")

    image_status = _request_json("GET", "/image/index/status", timeout=10)
    qdrant_status: dict[str, Any] = {}
    if image_status.get("ok"):
        qdrant_status = {
            "annoy_exists": image_status["data"].get("annoy_exists"),
            "indexed_images_annoy": image_status["data"].get("indexed_images"),
            "annoy_needs_rebuild": image_status["data"].get("annoy_needs_rebuild"),
        }

    return {
        "ok": True,
        "sources": {
            "base_dir": base_dir,
            "folders": {
                "text": [str(Path(base_dir) / f) for f in cfg["text_folders"]],
                "images": str(Path(base_dir) / cfg["image_folder"]),
                "videos": str(Path(base_dir) / cfg["video_folder"]),
                "audio": str(Path(base_dir) / cfg["audio_folder"]),
            },
            "connectors": {
                "filesystem": True,
                "qdrant": bool(qdrant_status),
                "rclone": True,
            },
        },
        "indexed_counts": {
            "text": doc_text_total,
            "audio": audio_total,
            "image": image_total,
            "video": video_total,
            "total": doc_text_total + audio_total + image_total + video_total,
        },
        "backend": {
            "base_url": BACKEND_BASE_URL,
            "image_index_status": qdrant_status,
        },
    }


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run()
        return
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
