"""
MCP adapter for ContextCore unified search backend.

Three tools only:
  1. search         - find relevant content across all indexed sources
  2. index_content  - trigger background indexing when content seems stale
  3. list_sources   - discover what connectors and paths are indexed
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP
from cli.constants import DEFAULT_BACKEND_URL

SERVER_NAME = "contextcore-unified"
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

VCS_MARKERS = (".git", ".hg", ".svn")
LANGUAGE_MANIFEST_MARKERS: dict[str, tuple[str, ...]] = {
    "node": ("package.json",),
    "python": ("pyproject.toml", "setup.py", "setup.cfg"),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "ruby": ("Gemfile",),
    "php": ("composer.json",),
    "elixir": ("mix.exs",),
    "dart": ("pubspec.yaml",),
    "dotnet": (".csproj", ".sln"),
    "c_cpp": ("CMakeLists.txt", "Makefile"),
}
FRAMEWORK_MARKERS = (
    "next.config.js",
    "vite.config.js",
    "webpack.config.js",
    "tsconfig.json",
    "angular.json",
    "vue.config.js",
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    "jest.config.js",
    "pytest.ini",
    "phpunit.xml",
)
COMMON_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "out",
    "target",
    "coverage",
}
EXCLUDES_BY_PROJECT_TYPE: dict[str, set[str]] = {
    "node": {"node_modules", ".next", "dist", "build", "coverage"},
    "python": {".venv", "venv", "__pycache__", ".eggs", "build", "dist", ".tox"},
    "rust": {"target"},
    "go": {"vendor", "bin"},
    "java": {"target", ".gradle", "build"},
    "ruby": {"vendor", ".bundle"},
    "php": {"vendor"},
    "dotnet": {"bin", "obj"},
    "c_cpp": {"build", "out"},
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
    # Deprecated: prefer list_sources() logic directly
    return {}


def _manifest_markers_at(path: Path) -> list[str]:
    markers: list[str] = []
    for marker in (
        "package.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Gemfile",
        "composer.json",
        "mix.exs",
        "pubspec.yaml",
        "CMakeLists.txt",
        "Makefile",
    ):
        if (path / marker).exists():
            markers.append(marker)

    for ext_marker in (".csproj", ".sln"):
        if list(path.glob(f"*{ext_marker}")):
            markers.append(ext_marker)
    return sorted(set(markers))


def _framework_markers_at(path: Path) -> list[str]:
    found: list[str] = []
    for marker in FRAMEWORK_MARKERS:
        if (path / marker).exists():
            found.append(marker)
    return sorted(found)


def _classify_project_types(root: Path) -> list[str]:
    types: list[str] = []
    for project_type, markers in LANGUAGE_MANIFEST_MARKERS.items():
        for marker in markers:
            if marker.startswith("."):
                if list(root.glob(f"*{marker}")):
                    types.append(project_type)
                    break
            elif (root / marker).exists():
                types.append(project_type)
                break
    return sorted(set(types))


def _find_project_root(start_path: Path) -> tuple[Path, dict[str, Any]]:
    current = start_path if start_path.is_dir() else start_path.parent
    chain = [current, *list(current.parents)]

    for p in chain:
        found_vcs = [m for m in VCS_MARKERS if (p / m).exists()]
        if found_vcs:
            return p, {"method": "vcs", "vcs_markers": found_vcs}

    for p in chain:
        manifests = _manifest_markers_at(p)
        if manifests:
            return p, {"method": "manifest", "manifest_markers": manifests}

    for p in chain:
        fw = _framework_markers_at(p)
        if fw:
            return p, {"method": "framework", "framework_markers": fw}

    return current, {"method": "fallback"}


def _classify_name_style(stem: str) -> str:
    if not stem:
        return "other"
    if re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)+", stem):
        return "snake"
    if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", stem):
        return "kebab"
    if re.fullmatch(r"[a-z]+([A-Z][a-z0-9]*)+", stem):
        return "camel"
    return "other"


def _scan_code_signals(root: Path, max_scan_files: int) -> dict[str, Any]:
    file_count = 0
    test_file_count = 0
    import_link_count = 0
    readme_present = any((root / n).exists() for n in ("README", "README.md", "README.txt"))
    changelog_present = any((root / n).exists() for n in ("CHANGELOG", "CHANGELOG.md", "HISTORY.md"))
    generated_or_dep_dirs: set[str] = set()
    name_style_counts = {"snake": 0, "kebab": 0, "camel": 0, "other": 0}
    base_names: set[str] = set()
    code_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        if file_count >= max_scan_files:
            break
        dirnames[:] = [d for d in dirnames if d not in COMMON_EXCLUDE_DIRS]
        generated_or_dep_dirs.update(d for d in dirnames if d in COMMON_EXCLUDE_DIRS)

        for fname in filenames:
            if file_count >= max_scan_files:
                break
            file_count += 1
            lower_name = fname.lower()
            stem = Path(fname).stem
            name_style_counts[_classify_name_style(stem)] += 1
            base_names.add(stem.lower())

            if (
                lower_name.startswith("test_")
                or lower_name.endswith("_test.py")
                or ".test." in lower_name
                or ".spec." in lower_name
            ):
                test_file_count += 1

            ext = Path(fname).suffix.lower()
            if ext in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".php", ".rb"}:
                code_files.append(Path(dirpath) / fname)

    for file_path in code_files[: min(len(code_files), 300)]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        content = text[:8000]
        matches = re.findall(r"(?:from|import|require|use|include)\s*(?:\(|from)?\s*['\"]([^'\"]+)['\"]", content)
        for module in matches:
            mod = module.strip().split("/")[-1].split(".")[-1].lower()
            if module.startswith((".", "/")) or mod in base_names:
                import_link_count += 1
                if import_link_count >= 10:
                    break
        if import_link_count >= 10:
            break

    dominant_style = max(name_style_counts, key=name_style_counts.get)
    dominant_count = name_style_counts[dominant_style]
    naming_consistent = file_count >= 8 and dominant_style != "other" and (dominant_count / max(file_count, 1)) >= 0.65

    return {
        "file_count_scanned": file_count,
        "test_file_count": test_file_count,
        "import_link_count": import_link_count,
        "readme_present": readme_present,
        "changelog_present": changelog_present,
        "generated_or_dependency_dirs_detected": sorted(generated_or_dep_dirs),
        "naming_consistent": naming_consistent,
        "dominant_name_style": dominant_style,
        "name_style_counts": name_style_counts,
        "scan_truncated": file_count >= max_scan_files,
    }


def _codebase_score(
    *,
    root_info: dict[str, Any],
    manifest_markers: list[str],
    framework_markers: list[str],
    scan_signals: dict[str, Any],
) -> tuple[int, dict[str, int]]:
    breakdown = {
        "vcs_marker": 40 if root_info.get("vcs_markers") else 0,
        "language_manifest": 30 if manifest_markers else 0,
        "framework_config": 20 if framework_markers else 0,
        "test_files": 15 if int(scan_signals.get("test_file_count", 0)) > 0 else 0,
        "inter_file_imports": 15 if int(scan_signals.get("import_link_count", 0)) > 0 else 0,
        "readme_or_changelog": 10 if scan_signals.get("readme_present") or scan_signals.get("changelog_present") else 0,
        "consistent_naming": 10 if scan_signals.get("naming_consistent") else 0,
        "generated_or_dependency_dirs": 10 if scan_signals.get("generated_or_dependency_dirs_detected") else 0,
    }
    return sum(breakdown.values()), breakdown


@mcp.tool()
def analyze_code_directory(
    path: str = ".",
    threshold: int = 40,
    max_scan_files: int = 5000,
) -> dict[str, Any]:
    """
    Analyze whether a directory is a software project and return codebase confidence + signals.
    Uses root-intent markers first, then fallback content signals for ambiguous folders.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"ok": False, "error": "path_not_found", "path": str(target)}
    if not target.is_dir():
        return {"ok": False, "error": "path_not_directory", "path": str(target)}

    bounded_threshold = max(0, min(int(threshold), 100))
    bounded_scan_limit = max(100, min(int(max_scan_files), 20000))

    project_root, root_info = _find_project_root(target)
    manifest_markers = _manifest_markers_at(project_root)
    framework_markers = _framework_markers_at(project_root)
    project_types = _classify_project_types(project_root)
    scan_signals = _scan_code_signals(project_root, bounded_scan_limit)
    score, score_breakdown = _codebase_score(
        root_info=root_info,
        manifest_markers=manifest_markers,
        framework_markers=framework_markers,
        scan_signals=scan_signals,
    )
    is_code_directory = score >= bounded_threshold

    exclusion_dirs = set(COMMON_EXCLUDE_DIRS)
    for ptype in project_types:
        exclusion_dirs.update(EXCLUDES_BY_PROJECT_TYPE.get(ptype, set()))

    confidence_band = "low"
    if score >= 40:
        confidence_band = "high"
    elif score >= 20:
        confidence_band = "medium"

    return {
        "ok": True,
        "input_path": str(target),
        "project_root": str(project_root),
        "is_code_directory": is_code_directory,
        "confidence_score": score,
        "confidence_threshold": bounded_threshold,
        "confidence_band": confidence_band,
        "root_detection": {
            "method": root_info.get("method"),
            "vcs_markers": root_info.get("vcs_markers", []),
            "manifest_markers": manifest_markers,
            "framework_markers": framework_markers,
        },
        "project_types": project_types,
        "score_breakdown": score_breakdown,
        "signals": scan_signals,
        "indexing_guidance": {
            "scope_rule": "Index all files under project_root except excluded directories.",
            "exclude_directories": sorted(exclusion_dirs),
        },
    }


@mcp.tool()
def get_codebase_context(
    repo_path: str = ".",
    force_reindex: bool = False,
    include_all: bool = True,
    files_limit: int = 500,
    symbols_limit: int = 2000,
    threshold: int = 40,
    max_scan_files: int = 5000,
) -> dict[str, Any]:
    """
    Return full structured Layer 1 + Layer 2 codebase context for agent reasoning.

    Use this at the start of codebase tasks. It returns deterministic facts only:
    project detection/classification + indexed repository/file/symbol data.
    """
    bounded_files_limit = max(1, min(int(files_limit), 20000))
    bounded_symbols_limit = max(1, min(int(symbols_limit), 100000))
    upstream = _request_json(
        "GET",
        "/index/code/context",
        params={
            "path": repo_path,
            "force_reindex": force_reindex,
            "include_all": include_all,
            "files_limit": bounded_files_limit,
            "symbols_limit": bounded_symbols_limit,
            "threshold": max(0, min(int(threshold), 100)),
            "max_scan_files": max(100, min(int(max_scan_files), 20000)),
        },
        timeout=120,
    )
    return upstream


@mcp.tool()
def get_codebase_index(
    repo_path: str = ".",
    recent_days: int = 7,
    recent_limit: int = 20,
    symbol_limit: int = 1200,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """
    First-call orientation tool.
    Returns structure, symbols index, external deps, and recent changes.
    """
    return _request_json(
        "GET",
        "/index/code/get_codebase_index",
        params={
            "path": repo_path,
            "recent_days": max(1, min(int(recent_days), 90)),
            "recent_limit": max(1, min(int(recent_limit), 100)),
            "symbol_limit": max(1, min(int(symbol_limit), 10000)),
            "force_reindex": force_reindex,
        },
        timeout=120,
    )


@mcp.tool()
def get_module_detail(
    repo_path: str,
    paths: list[str],
) -> dict[str, Any]:
    """
    Targeted module detail tool.
    Returns full symbol + import details only for requested relative paths.
    """
    cleaned = [str(p).replace("\\", "/").strip() for p in paths if str(p).strip()]
    return _request_json(
        "POST",
        "/index/code/get_module_detail",
        json_body={
            "repo_path": repo_path,
            "paths": cleaned,
        },
        timeout=120,
    )


@mcp.tool()
def get_file_content(
    repo_path: str,
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, Any]:
    """
    Raw source read tool for specific file path and optional line range.
    """
    params: dict[str, Any] = {
        "repo_path": repo_path,
        "path": path,
        "start_line": max(1, int(start_line)),
    }
    if end_line is not None:
        params["end_line"] = max(1, int(end_line))
    return _request_json(
        "GET",
        "/index/code/get_file_content",
        params=params,
        timeout=60,
    )


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
                    "description": r.get("description", ""),
                    "best_timestamp": r.get("best_timestamp"),
                    "transcript_match": r.get("transcript_match", False),
                    "context_match": r.get("context_match", False),
                    "ocr_text": r.get("ocr_text", ""),
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
def fetch_content(
    path: str,
    modality: str = "auto",
) -> dict[str, Any]:
    """
    Fetch readable content or metadata for a specific file found via search.

    For video files: returns frame descriptions, timestamps, and transcript
    excerpts so the agent can understand what is in the video without needing
    to play it.

    For text/audio files: returns the indexed content/transcript.

    For image files: returns the file path for direct access by local tools.

    WHEN TO CALL:
    Call this after search() returns a result and you need more detail about
    a specific file — especially for videos where the search result only has
    a score and brief description.

    PARAMETERS:
    - path: the absolute source path from a search result
    - modality: "auto" (detect from extension), "video", "text", "image"
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"ok": False, "error": "file_not_found", "path": str(p)}

    # Auto-detect modality
    if modality == "auto":
        ext = p.suffix.lower()
        if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
            modality = "video"
        elif ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}:
            modality = "image"
        else:
            modality = "text"

    if modality == "video":
        return _fetch_video_content(str(p))
    elif modality == "image":
        return {
            "ok": True,
            "modality": "image",
            "path": str(p),
            "filename": p.name,
            "next_step": "Use prepare_file_for_tool to access this image.",
        }
    else:
        return _fetch_text_content(str(p))


def _fetch_video_content(video_path: str) -> dict[str, Any]:
    """Retrieve indexed frame descriptions and transcript for a video."""
    try:
        video_db = PROJECT_ROOT / "video_search_implementation_v2" / "storage" / "videos_meta.db"
        if not video_db.exists():
            return {"ok": False, "error": "video_index_not_found"}

        import sqlite3
        conn = sqlite3.connect(str(video_db))
        conn.row_factory = sqlite3.Row

        video_row = conn.execute(
            "SELECT id FROM videos WHERE path = ?", (video_path,)
        ).fetchone()
        if not video_row:
            conn.close()
            return {"ok": False, "error": "video_not_indexed", "path": video_path}

        frames = conn.execute(
            "SELECT timestamp, description, ocr_text FROM frames WHERE video_id = ? ORDER BY timestamp",
            (video_row["id"],),
        ).fetchall()
        conn.close()

        frame_summaries = []
        for f in frames:
            ts = f["timestamp"]
            ts_str = f"{ts:.1f}s" if ts and ts >= 0 else "unknown"
            frame_summaries.append({
                "timestamp": ts_str,
                "description": f["description"] or "no description",
                "ocr_text": (f["ocr_text"] or "").strip(),
            })

        # Try to get transcript from text FTS
        transcript = None
        try:
            text_db = PROJECT_ROOT / "text_search_implementation_v2" / "storage" / "text_search_implementation_v2.db"
            if text_db.exists():
                tconn = sqlite3.connect(str(text_db))
                tconn.row_factory = sqlite3.Row
                trow = tconn.execute(
                    "SELECT content FROM files WHERE path = ? AND category = 'video_transcript'",
                    (video_path,),
                ).fetchone()
                if trow:
                    transcript = trow["content"]
                tconn.close()
        except Exception:
            pass

        return {
            "ok": True,
            "modality": "video",
            "path": video_path,
            "filename": Path(video_path).name,
            "frame_count": len(frame_summaries),
            "frames": frame_summaries[:20],  # Cap at 20 for context window
            "transcript_available": transcript is not None,
            "transcript_excerpt": (transcript[:2000] + "...") if transcript and len(transcript) > 2000 else transcript,
            "context_available": any(frame.get("description") or frame.get("ocr_text") for frame in frame_summaries),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_text_content(file_path: str) -> dict[str, Any]:
    """Retrieve indexed text content for a file."""
    try:
        text_db = PROJECT_ROOT / "text_search_implementation_v2" / "storage" / "text_search_implementation_v2.db"
        if not text_db.exists():
            return {"ok": False, "error": "text_index_not_found"}

        import sqlite3
        conn = sqlite3.connect(str(text_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT filename, category, content FROM files WHERE path = ?",
            (file_path,),
        ).fetchone()
        conn.close()

        if not row:
            return {"ok": False, "error": "file_not_indexed", "path": file_path}

        content = row["content"] or ""
        return {
            "ok": True,
            "modality": "text",
            "path": file_path,
            "filename": row["filename"],
            "category": row["category"],
            "content": content[:5000],  # Cap for context window
            "content_truncated": len(content) > 5000,
            "total_length": len(content),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
    target_dir: str | None = None,
) -> dict[str, Any]:
    """
    Trigger a background scan to index new or updated files from all
    configured sources, or a specific directory if provided. Returns immediately.

    WHEN TO CALL:
    Only call this if:
    - The user explicitly says content is missing from search results
    - The user says "re-index", "refresh", or "scan my files"
    - The user asks to index a specific folder (use target_dir)

    Do NOT call this proactively before every search.
    """
    params = {
        "run_text": run_text,
        "run_image": run_image,
        "run_video": run_video,
        "run_audio": run_audio,
    }
    if target_dir:
        params["target_dir"] = target_dir

    return _request_json(
        "POST",
        "/index/scan",
        params=params,
        timeout=30,
    )


@mcp.tool()
def list_sources() -> dict[str, Any]:
    """
    Return what content sources are currently configured and indexed -
    folders being watched, connectors active, and a count of indexed
    items per modality.
    """
    try:
        from config import get_organized_root, get_video_directories, get_audio_directories, get_image_directory
        base_dir = str(get_organized_root())
        text_folders = ["docs", "spreadsheets", "code"]
        
        def _rel(p):
            try: return str(p.relative_to(get_organized_root()))
            except ValueError: return str(p)
            
        folders_cfg = {
            "text": [str(get_organized_root() / f) for f in text_folders],
            "images": str(get_image_directory()),
            "videos": [str(p) for p in get_video_directories()],
            "audio": [str(p) for p in get_audio_directories()],
        }
    except Exception:
        base_dir = "."
        folders_cfg = {}

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
            "folders": folders_cfg,
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
