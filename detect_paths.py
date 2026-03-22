#!/usr/bin/env python3
"""
detect_paths.py - deterministic path detector for ContextCore MCP setup.

Usage:
    python detect_paths.py
    python detect_paths.py --json
    python detect_paths.py --mcp-config
    python detect_paths.py --claude-json
    python detect_paths.py --shell
    python detect_paths.py --validate
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
from typing import Callable


def _is_virtual_env() -> bool:
    return (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )


def _is_conda_env() -> bool:
    return "CONDA_PREFIX" in os.environ or "CONDA_DEFAULT_ENV" in os.environ


def _is_pipx_env() -> bool:
    exe = sys.executable.lower()
    prefix = str(sys.prefix).lower()
    return "pipx" in exe or "pipx" in prefix


def _detect_env_type() -> str:
    if _is_pipx_env():
        return "pipx"
    if _is_conda_env():
        return "conda"
    if _is_virtual_env():
        return "virtualenv"
    exe = sys.executable.lower()
    if "homebrew" in exe or "/opt/homebrew" in exe:
        return "homebrew"
    if "/usr/local/bin" in exe or "/usr/bin" in exe:
        return "system"
    if "appdata" in exe or "program files" in exe:
        return "system-windows"
    return "user-install"


def get_python_path() -> dict:
    return {
        "path": sys.executable,
        "version": platform.python_version(),
        "is_venv": _is_virtual_env(),
        "is_conda": _is_conda_env(),
        "is_pipx": _is_pipx_env(),
        "env_type": _detect_env_type(),
        "platform": platform.system(),
    }


def _try_env_override() -> pathlib.Path | None:
    val = os.environ.get("CONTEXTCORE_MCP_SCRIPT")
    return pathlib.Path(val).expanduser() if val else None


def _try_sibling_of_script() -> pathlib.Path | None:
    return pathlib.Path(__file__).resolve().parent / "mcp_server.py"


def _try_parent_of_cli_dir() -> pathlib.Path | None:
    # If copied under cli/, fallback to repo root candidate.
    # cli/detect_paths.py -> ../mcp_server.py
    return pathlib.Path(__file__).resolve().parent.parent / "mcp_server.py"


def _walk_for_mcp_from(base: pathlib.Path, max_up: int = 6) -> pathlib.Path | None:
    current = base.resolve()
    for _ in range(max_up):
        candidate = current / "mcp_server.py"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _try_site_packages() -> pathlib.Path | None:
    # Strategy: locate installed package/module and walk upward.
    try:
        import importlib.util

        for pkg_name in ("mcp_server", "cli.main", "cli"):
            spec = importlib.util.find_spec(pkg_name)
            if not spec:
                continue
            origin = None
            if spec.origin and spec.origin != "built-in":
                origin = pathlib.Path(spec.origin)
            elif spec.submodule_search_locations:
                first = next(iter(spec.submodule_search_locations), None)
                if first:
                    origin = pathlib.Path(first)
            if origin:
                found = _walk_for_mcp_from(origin if origin.is_dir() else origin.parent)
                if found:
                    return found
    except Exception:
        return None
    return None


def _try_which_contextcore() -> pathlib.Path | None:
    exe = shutil.which("contextcore")
    if not exe:
        return None
    bin_path = pathlib.Path(exe).resolve()
    found = _walk_for_mcp_from(bin_path.parent)
    if found:
        return found
    # Common editable install layout: <repo>/.venv/bin/contextcore
    try:
        if ".venv" in str(bin_path):
            parts = list(bin_path.parts)
            idx = parts.index(".venv")
            repo_root = pathlib.Path(*parts[:idx])
            candidate = repo_root / "mcp_server.py"
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return None


def _try_common_locations() -> pathlib.Path | None:
    home = pathlib.Path.home()
    candidates = [
        home / ".contextcore" / "mcp_server.py",
        home / "contextcore" / "mcp_server.py",
        home / "SearchEmbedSDK" / "mcp_server.py",
        home / "Documents" / "SDKSearchImplementation" / "SearchEmbedSDK" / "mcp_server.py",
        pathlib.Path.cwd() / "mcp_server.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def get_mcp_server_path() -> dict:
    methods: list[tuple[str, Callable[[], pathlib.Path | None]]] = [
        ("env_override", _try_env_override),
        ("sibling_of_script", _try_sibling_of_script),
        ("parent_of_cli_dir", _try_parent_of_cli_dir),
        ("site_packages", _try_site_packages),
        ("which_contextcore", _try_which_contextcore),
        ("common_locations", _try_common_locations),
    ]
    for method_name, method_fn in methods:
        path = method_fn()
        if path and path.exists():
            return {"path": str(path.resolve()), "found_via": method_name, "exists": True}
    return {
        "path": None,
        "found_via": None,
        "exists": False,
        "error": "mcp_server.py not found. Is ContextCore installed correctly?",
    }


def validate_setup(python_info: dict, mcp_info: dict) -> list[str]:
    issues: list[str] = []

    major, minor, *_ = [int(p) for p in python_info["version"].split(".")]
    if major < 3 or (major == 3 and minor < 10):
        issues.append(
            f"Python {python_info['version']} detected. ContextCore requires Python 3.10+."
        )

    if not mcp_info["exists"]:
        issues.append(
            "mcp_server.py not found. Install ContextCore or set CONTEXTCORE_MCP_SCRIPT."
        )

    missing: list[str] = []
    for dep in ("mcp", "fastapi", "requests"):
        try:
            __import__(dep)
        except Exception:
            missing.append(dep)
    if missing:
        issues.append(
            f"Missing Python packages: {', '.join(missing)}. Run: {sys.executable} -m pip install -r requirements.txt"
        )

    if not python_info["is_venv"] and not python_info["is_conda"] and not python_info["is_pipx"]:
        issues.append(
            "Not running inside venv/conda/pipx. Using an isolated environment is recommended."
        )

    return issues


def format_mcp_config_block(python_path: str, mcp_path: str) -> str:
    entry = {
        "contextcore": {
            "type": "stdio",
            "command": python_path,
            "args": [mcp_path],
        }
    }
    return json.dumps(entry, indent=2)


def format_shell_exports(python_path: str, mcp_path: str) -> str:
    if platform.system() == "Windows":
        return (
            f'$env:CONTEXTCORE_PYTHON="{python_path}"\n'
            f'$env:CONTEXTCORE_MCP_SCRIPT="{mcp_path}"'
        )
    return (
        f'export CONTEXTCORE_PYTHON="{python_path}"\n'
        f'export CONTEXTCORE_MCP_SCRIPT="{mcp_path}"'
    )


def format_full_claude_json(python_path: str, mcp_path: str) -> str:
    cfg = {
        "mcpServers": {
            "contextcore": {
                "type": "stdio",
                "command": python_path,
                "args": [mcp_path],
            }
        }
    }
    return json.dumps(cfg, indent=2)


def _default_output(python_info: dict, mcp_info: dict, issues: list[str]) -> int:
    python_path = python_info["path"]
    mcp_path = mcp_info.get("path")
    sep = "-" * 60
    print(sep)
    print("ContextCore Path Detection")
    print(sep)
    print("\nPython executable:")
    print(f"  Path:    {python_path}")
    print(f"  Version: {python_info['version']}")
    print(f"  Type:    {python_info['env_type']}")

    print("\nMCP server (mcp_server.py):")
    if mcp_path:
        print(f"  Path:      {mcp_path}")
        print(f"  Found via: {mcp_info['found_via']}")
    else:
        print("  NOT FOUND")
        print(f"  Error: {mcp_info.get('error', 'unknown')}")

    print("\nValidation:")
    if not issues:
        print("  OK: all checks passed")
    else:
        for issue in issues:
            print(f"  ISSUE: {issue}")

    if mcp_path:
        print("\nQuick reference:")
        print(f"  Python: {python_path}")
        print(f"  Script: {mcp_path}")
        print("  Run with --mcp-config for JSON block.")
        print("  Run with --claude-json for ~/.claude.json block.")
    print(sep)
    return 0 if mcp_info["exists"] and not issues else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect Python and mcp_server.py paths for MCP configuration."
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--mcp-config", action="store_true", help="Output JSON for mcpServers.contextcore.")
    parser.add_argument("--claude-json", action="store_true", help="Output complete ~/.claude.json content.")
    parser.add_argument("--shell", action="store_true", help="Output shell export commands.")
    parser.add_argument("--validate", action="store_true", help="Validation checks only.")
    args = parser.parse_args()

    python_info = get_python_path()
    mcp_info = get_mcp_server_path()
    issues = validate_setup(python_info, mcp_info)

    python_path = python_info["path"]
    mcp_path = mcp_info.get("path")

    if args.json:
        payload = {"python": python_info, "mcp_server": mcp_info, "validation": issues}
        print(json.dumps(payload, indent=2))
        return 0 if mcp_info["exists"] and not issues else 1

    if args.validate:
        if not issues:
            print("OK: all checks passed")
            return 0
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"- {issue}")
        return 1

    if args.mcp_config:
        if not mcp_path:
            print("Error: mcp_server.py not found.", file=sys.stderr)
            return 1
        print(format_mcp_config_block(python_path, mcp_path))
        return 0

    if args.claude_json:
        if not mcp_path:
            print("Error: mcp_server.py not found.", file=sys.stderr)
            return 1
        print(format_full_claude_json(python_path, mcp_path))
        return 0

    if args.shell:
        if not mcp_path:
            print("Error: mcp_server.py not found.", file=sys.stderr)
            return 1
        print(format_shell_exports(python_path, mcp_path))
        return 0

    return _default_output(python_info, mcp_info, issues)


if __name__ == "__main__":
    sys.exit(main())
