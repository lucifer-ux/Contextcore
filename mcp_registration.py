#!/usr/bin/env python3
"""
One-command MCP registration helper.

Examples:
  python mcp_registration.py --claude-desktop
  python mcp_registration.py --cline
  python mcp_registration.py --cursor --backend-url http://127.0.0.1:8000
  python mcp_registration.py --tool chatgpt --config "C:\\path\\to\\config.json"
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SUPPORTED_TOOLS = (
    "claude-desktop",
    "claude.ai",
    "cline",
    "cursor",
    "continue",
    "windsurf",
    "chatgpt",
    "chatgpt-web",
    "codex",
    "claude-code",
    "antigravity",
    "aider",
    "opencode",
    "goose",
    "gemini-web",
    "perplexity",
    "browser-chat",
)


def _env_path(name: str) -> Path:
    val = os.getenv(name, "")
    return Path(val) if val else Path()


def _default_candidates(tool: str) -> list[Path]:
    appdata = _env_path("APPDATA")
    localappdata = _env_path("LOCALAPPDATA")
    userprofile = _env_path("USERPROFILE")

    if tool == "claude-desktop":
        return [
            appdata / "Claude" / "claude_desktop_config.json",
            localappdata / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json",
        ]
    if tool == "cline":
        return [
            appdata / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
            appdata / "Code - Insiders" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        ]
    if tool == "cursor":
        return [
            appdata / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
            appdata / "Cursor" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
        ]
    if tool == "chatgpt":
        return [
            appdata / "ChatGPT" / "chatgpt_config.json",
            localappdata / "ChatGPT" / "chatgpt_config.json",
        ]
    if tool == "chatgpt-web":
        return []
    if tool == "codex":
        return [
            userprofile / ".codex" / "config.json",
            appdata / "Codex" / "config.json",
        ]
    if tool == "claude-code":
        return [
            userprofile / ".claude" / "config.json",
            appdata / "Claude Code" / "config.json",
        ]
    if tool == "antigravity":
        return [
            appdata / "Antigravity" / "config.json",
            localappdata / "Antigravity" / "config.json",
        ]
    if tool == "continue":
        return [
            appdata / "Code" / "User" / "globalStorage" / "continue.continue" / "config.json",
            appdata / "Cursor" / "User" / "globalStorage" / "continue.continue" / "config.json",
        ]
    if tool == "windsurf":
        return [
            appdata / "Windsurf" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        ]
    if tool == "aider":
        return [userprofile / ".aider.conf.json"]
    if tool == "opencode":
        return [userprofile / ".opencode" / "config.json"]
    if tool == "goose":
        return [appdata / "Goose" / "config.json", userprofile / ".goose" / "config.json"]
    if tool in {"claude.ai", "gemini-web", "perplexity", "browser-chat"}:
        return []
    return []


def _pick_target_path(tool: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()

    candidates = [p for p in _default_candidates(tool) if str(p) not in ("", ".")]
    existing = [p for p in candidates if p.exists()]
    if existing:
        return existing[0]
    if candidates:
        return candidates[0]
    raise ValueError(
        f"No default config path candidates for tool '{tool}'. "
        "This tool may be web-only or unknown; use --config only if it supports local MCP config."
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a JSON object: {path}")
    return data


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak_{ts}")
    shutil.copy2(path, bak)
    return bak


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_python(project_root: Path) -> str:
    if os.name == "nt":
        venv_py = project_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = project_root / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _server_entry(project_root: Path, backend_url: str, timeout_seconds: int) -> dict[str, Any]:
    return {
        "command": _resolve_python(project_root),
        "args": [str((project_root / "mcp_server.py").resolve())],
        "env": {
            "CONTEXTCORE_API_BASE_URL": backend_url,
            "CONTEXTCORE_MCP_TIMEOUT_SECONDS": str(timeout_seconds),
        },
    }


def _selected_tools(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    if args.all:
        return list(SUPPORTED_TOOLS)
    if args.claude_desktop:
        out.append("claude-desktop")
    if args.cline:
        out.append("cline")
    if args.cursor:
        out.append("cursor")
    if args.chatgpt:
        out.append("chatgpt")
    if args.codex:
        out.append("codex")
    if args.claude_code:
        out.append("claude-code")
    if args.antigravity:
        out.append("antigravity")
    if args.tool:
        out.append(args.tool)
    return list(dict.fromkeys(out))


def _register_one(
    *,
    tool: str,
    config_path: Path,
    server_name: str,
    entry: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    data = _read_json(config_path)
    mcp_servers = data.get("mcpServers")
    if mcp_servers is None:
        mcp_servers = {}
        data["mcpServers"] = mcp_servers
    if not isinstance(mcp_servers, dict):
        raise ValueError(f"'mcpServers' must be an object in {config_path}")

    existed = server_name in mcp_servers
    mcp_servers[server_name] = entry

    backup_path = None
    if not dry_run:
        _ensure_parent(config_path)
        backup_path = _backup(config_path)
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "tool": tool,
        "config_path": str(config_path),
        "action": "updated" if existed else "added",
        "backup": str(backup_path) if backup_path else None,
        "dry_run": dry_run,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Register ContextCore MCP server config for local clients")
    p.add_argument("--claude-desktop", action="store_true")
    p.add_argument("--cline", action="store_true")
    p.add_argument("--cursor", action="store_true")
    p.add_argument("--chatgpt", action="store_true")
    p.add_argument("--codex", action="store_true")
    p.add_argument("--claude-code", action="store_true")
    p.add_argument("--antigravity", action="store_true")
    p.add_argument("--all", action="store_true", help="Register for all known tools")
    p.add_argument("--tool", choices=SUPPORTED_TOOLS, help="Alternative to a specific flag")
    p.add_argument("--config", help="Override target config path (single-tool use)")
    p.add_argument("--server-name", default="contextcore", help="MCP server key name under mcpServers")
    p.add_argument("--backend-url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    tools = _selected_tools(args)

    if not tools:
        parser.error("Select at least one target using flags like --claude-desktop, --cline, or --all")

    if args.config and len(tools) != 1:
        parser.error("--config can only be used when exactly one tool is selected")

    project_root = Path(__file__).resolve().parent
    entry = _server_entry(project_root, args.backend_url, args.timeout_seconds)

    results = []
    for tool in tools:
        target = _pick_target_path(tool, args.config)
        results.append(
            _register_one(
                tool=tool,
                config_path=target,
                server_name=args.server_name,
                entry=entry,
                dry_run=args.dry_run,
            )
        )

    print(json.dumps({"ok": True, "results": results}, indent=2))
    print("\nNext steps:")
    print("1) Keep backend running: uvicorn unimain:app --host 127.0.0.1 --port 8000")
    print("2) Restart the target client app so MCP config reloads.")


if __name__ == "__main__":
    main()
