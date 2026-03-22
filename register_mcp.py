#!/usr/bin/env python3
"""
register_mcp.py - cross-platform ContextCore MCP registration helper.

Examples:
  python register_mcp.py
  python register_mcp.py --tool claude-code
  python register_mcp.py --list
  python register_mcp.py --dry-run
  python register_mcp.py --unregister
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import sys
from datetime import datetime
from typing import Any, Optional


SERVER_NAME = "contextcore"

IS_WINDOWS = platform.system() == "Windows"
HOME = pathlib.Path.home()
APPDATA = pathlib.Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
LOCALAPPDATA = pathlib.Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))


def resolve_python() -> str:
    return str(pathlib.Path(sys.executable).resolve())


def resolve_mcp_server() -> str:
    # 1) Explicit override
    override = os.environ.get("CONTEXTCORE_MCP_SCRIPT")
    if override:
        p = pathlib.Path(override).expanduser().resolve()
        if p.exists():
            return str(p)

    # 2) Reuse deterministic detector if available
    try:
        from detect_paths import get_mcp_server_path  # type: ignore

        data = get_mcp_server_path()
        p = data.get("path")
        if isinstance(p, str) and pathlib.Path(p).exists():
            return str(pathlib.Path(p).resolve())
    except Exception:
        pass

    this_file = pathlib.Path(__file__).resolve()

    # 3) Sibling of this script
    candidate = this_file.parent / "mcp_server.py"
    if candidate.exists():
        return str(candidate)

    # 4) Parent directory
    candidate = this_file.parent.parent / "mcp_server.py"
    if candidate.exists():
        return str(candidate)

    # 5) site-packages / module discovery
    try:
        import importlib.util

        for pkg_name in ("mcp_server", "cli.main", "cli"):
            spec = importlib.util.find_spec(pkg_name)
            if not spec:
                continue
            origin = spec.origin
            if not origin:
                continue
            base = pathlib.Path(origin).parent
            for _ in range(6):
                candidate = base / "mcp_server.py"
                if candidate.exists():
                    return str(candidate.resolve())
                if base.parent == base:
                    break
                base = base.parent
    except Exception:
        pass

    # 6) common install locations
    candidates = [
        HOME / ".contextcore" / "mcp_server.py",
        HOME / "SearchEmbedSDK" / "mcp_server.py",
        HOME / "Documents" / "SDKSearchImplementation" / "SearchEmbedSDK" / "mcp_server.py",
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())

    raise FileNotFoundError(
        "mcp_server.py not found. Set CONTEXTCORE_MCP_SCRIPT or install ContextCore correctly."
    )


def get_tool_definitions() -> dict[str, dict[str, Any]]:
    return {
        "claude-desktop": {
            "display_name": "Claude Desktop",
            "config_paths": [
                HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
                APPDATA / "Claude" / "claude_desktop_config.json",
                LOCALAPPDATA / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json",
                HOME / ".config" / "Claude" / "claude_desktop_config.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Claude Desktop after registering.",
        },
        "claude-code": {
            "display_name": "Claude Code",
            "config_paths": [
                HOME / ".claude.json",
                HOME / ".claude" / "config.json",
                APPDATA / "Claude Code" / "config.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Claude Code and run /mcp.",
        },
        "cline": {
            "display_name": "Cline (VS Code)",
            "config_paths": [
                HOME / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                APPDATA / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                APPDATA / "Code - Insiders" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Reload VS Code after registering.",
        },
        "roo-code": {
            "display_name": "Roo Code (VS Code)",
            "config_paths": [
                HOME / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                APPDATA / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                HOME / ".config" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Reload VS Code after registering.",
        },
        "cursor": {
            "display_name": "Cursor",
            "config_paths": [
                APPDATA / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                APPDATA / "Cursor" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
                HOME / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / ".config" / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / ".cursor" / "mcp.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Cursor after registering.",
        },
        "windsurf": {
            "display_name": "Windsurf",
            "config_paths": [
                APPDATA / "Windsurf" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / "Library" / "Application Support" / "Windsurf" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / ".config" / "Windsurf" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
                HOME / ".codeium" / "windsurf" / "mcp_config.json",
                HOME / ".windsurf" / "mcp.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Windsurf after registering.",
        },
        "opencode": {
            "display_name": "OpenCode",
            "config_paths": [
                HOME / ".opencode" / "config.json",
                HOME / ".config" / "opencode" / "opencode.json",
                HOME / ".config" / "opencode" / "opencode.jsonc",
                APPDATA / "opencode" / "opencode.json",
            ],
            "config_format": "opencode_mcp",
            "notes": "Restart OpenCode after registering.",
        },
        "codex": {
            "display_name": "Codex CLI",
            "config_paths": [
                HOME / ".codex" / "config.json",
                APPDATA / "Codex" / "config.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Codex will use MCP on next invocation.",
        },
        "continue": {
            "display_name": "Continue",
            "config_paths": [
                HOME / ".continue" / "config.json",
                APPDATA / "Code" / "User" / "globalStorage" / "continue.continue" / "config.json",
                APPDATA / "Cursor" / "User" / "globalStorage" / "continue.continue" / "config.json",
            ],
            "config_format": "continue_mcp",
            "notes": "Reload Continue after registering.",
        },
        "gemini-cli": {
            "display_name": "Gemini CLI",
            "config_paths": [
                HOME / ".gemini" / "settings.json",
                HOME / ".config" / "gemini" / "settings.json",
                APPDATA / "gemini" / "settings.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Gemini CLI session after registering.",
        },
        "zed": {
            "display_name": "Zed Editor",
            "config_paths": [
                HOME / ".config" / "zed" / "settings.json",
                HOME / "Library" / "Application Support" / "Zed" / "settings.json",
                APPDATA / "Zed" / "settings.json",
            ],
            "config_format": "zed_context_server",
            "notes": "Restart Zed after registering.",
        },
        "goose": {
            "display_name": "Goose",
            "config_paths": [
                HOME / ".config" / "goose" / "profiles.yaml",
                HOME / ".goose" / "profiles.yaml",
                APPDATA / "goose" / "profiles.yaml",
            ],
            "config_format": "goose_mcp",
            "notes": "Restart Goose after registering.",
        },
        "amp": {
            "display_name": "Amp",
            "config_paths": [
                HOME / ".amp" / "config.json",
                HOME / ".config" / "amp" / "config.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Amp after registering.",
        },
        "pearai": {
            "display_name": "PearAI",
            "config_paths": [
                HOME / "Library" / "Application Support" / "PearAI" / "pearai_config.json",
                APPDATA / "PearAI" / "pearai_config.json",
                HOME / ".config" / "PearAI" / "pearai_config.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart PearAI after registering.",
        },
        "augment": {
            "display_name": "Augment",
            "config_paths": [
                HOME / ".augment" / "mcp.json",
                HOME / "Library" / "Application Support" / "Augment" / "mcp.json",
                APPDATA / "Augment" / "mcp.json",
            ],
            "config_format": "mcpServers_stdio",
            "notes": "Restart Augment after registering.",
        },
    }


def build_stdio_entry(python_path: str, mcp_script: str) -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": python_path,
        "args": [mcp_script],
        "env": {},
    }


def build_opencode_entry(python_path: str, mcp_script: str) -> dict[str, Any]:
    return {
        "type": "local",
        "command": [python_path, mcp_script],
        "environment": {},
    }


def build_continue_entry(python_path: str, mcp_script: str) -> dict[str, Any]:
    return {"name": SERVER_NAME, "command": python_path, "args": [mcp_script]}


def build_zed_entry(python_path: str, mcp_script: str) -> dict[str, Any]:
    return {"command": {"path": python_path, "args": [mcp_script]}}


def build_goose_entry(python_path: str, mcp_script: str) -> dict[str, Any]:
    return {
        "command": python_path,
        "args": [mcp_script],
        "description": "ContextCore local-first multimodal search",
    }


def _read_json_safe(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def _backup_file(path: pathlib.Path) -> Optional[pathlib.Path]:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak_{ts}")
    shutil.copy2(path, backup)
    return backup


def write_mcpservers_stdio(config_path: pathlib.Path, python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    data = _read_json_safe(config_path)
    mcp_servers = data.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
        data["mcpServers"] = mcp_servers
    mcp_servers[SERVER_NAME] = build_stdio_entry(python_path, mcp_script)
    if dry_run:
        print(f"  [dry-run] Would write: {config_path}")
        return True
    backup = _backup_file(config_path)
    if backup:
        print(f"  Backup: {backup.name}")
    _write_json_atomic(config_path, data)
    return True


def write_opencode_mcp(config_path: pathlib.Path, python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    data = _read_json_safe(config_path)
    mcp_obj = data.get("mcp")
    if not isinstance(mcp_obj, dict):
        mcp_obj = {}
        data["mcp"] = mcp_obj
    mcp_obj[SERVER_NAME] = build_opencode_entry(python_path, mcp_script)
    if isinstance(data.get("mcpServers"), dict):
        data.pop("mcpServers", None)
    if dry_run:
        print(f"  [dry-run] Would write: {config_path}")
        return True
    backup = _backup_file(config_path)
    if backup:
        print(f"  Backup: {backup.name}")
    _write_json_atomic(config_path, data)
    return True


def write_continue_mcp(config_path: pathlib.Path, python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    data = _read_json_safe(config_path)
    servers = data.get("mcpServers")
    if not isinstance(servers, list):
        servers = []
        data["mcpServers"] = servers
    servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == SERVER_NAME)]
    servers.append(build_continue_entry(python_path, mcp_script))
    data["mcpServers"] = servers
    if dry_run:
        print(f"  [dry-run] Would write: {config_path}")
        return True
    backup = _backup_file(config_path)
    if backup:
        print(f"  Backup: {backup.name}")
    _write_json_atomic(config_path, data)
    return True


def write_zed_context_server(config_path: pathlib.Path, python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    data = _read_json_safe(config_path)
    context_servers = data.get("context_servers")
    if not isinstance(context_servers, dict):
        context_servers = {}
        data["context_servers"] = context_servers
    context_servers[SERVER_NAME] = build_zed_entry(python_path, mcp_script)
    if dry_run:
        print(f"  [dry-run] Would write: {config_path}")
        return True
    backup = _backup_file(config_path)
    if backup:
        print(f"  Backup: {backup.name}")
    _write_json_atomic(config_path, data)
    return True


def write_goose_mcp(config_path: pathlib.Path, python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None

    if dry_run:
        print(f"  [dry-run] Would write: {config_path}")
        return True

    config_path.parent.mkdir(parents=True, exist_ok=True)
    entry = build_goose_entry(python_path, mcp_script)

    if yaml is None:
        lines = [
            "",
            "# ContextCore MCP added by register_mcp.py",
            "mcp_servers:",
            f"  {SERVER_NAME}:",
            f"    command: \"{python_path}\"",
            "    args:",
            f"      - \"{mcp_script}\"",
            "    description: ContextCore local-first multimodal search",
            "",
        ]
        with config_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return True

    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}
    existing.setdefault("mcp_servers", {})
    if not isinstance(existing["mcp_servers"], dict):
        existing["mcp_servers"] = {}
    existing["mcp_servers"][SERVER_NAME] = entry

    backup = _backup_file(config_path)
    if backup:
        print(f"  Backup: {backup.name}")
    config_path.write_text(yaml.dump(existing, default_flow_style=False), encoding="utf-8")
    return True


FORMAT_WRITERS = {
    "mcpServers_stdio": write_mcpservers_stdio,
    "opencode_mcp": write_opencode_mcp,
    "continue_mcp": write_continue_mcp,
    "zed_context_server": write_zed_context_server,
    "goose_mcp": write_goose_mcp,
}


def find_config_path(tool_def: dict[str, Any]) -> Optional[pathlib.Path]:
    candidates = [pathlib.Path(p).expanduser() for p in tool_def.get("config_paths", [])]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else None


def detect_installed_tools(tools: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for name, spec in tools.items():
        for p in spec.get("config_paths", []):
            if pathlib.Path(p).expanduser().exists():
                out.append(name)
                break
    return out


def register_tool(tool_name: str, tool_def: dict[str, Any], python_path: str, mcp_script: str, dry_run: bool = False) -> bool:
    config_path = find_config_path(tool_def)
    if config_path is None:
        print(f"  [X] No config path for {tool_name}")
        return False
    writer = FORMAT_WRITERS.get(tool_def.get("config_format"))
    if writer is None:
        print(f"  [X] Unknown config format for {tool_name}")
        return False
    try:
        writer(config_path, python_path, mcp_script, dry_run=dry_run)
        if not dry_run:
            print(f"  [OK] {config_path}")
            note = tool_def.get("notes")
            if note:
                print(f"      {note}")
        return True
    except PermissionError:
        print(f"  [X] Permission denied: {config_path}")
        return False
    except Exception as exc:
        print(f"  [X] Failed for {tool_name}: {exc}")
        return False


def unregister_tool(tool_name: str, tool_def: dict[str, Any], dry_run: bool = False) -> bool:
    config_path = find_config_path(tool_def)
    if config_path is None or not config_path.exists():
        return False
    fmt = tool_def.get("config_format")
    if fmt in ("mcpServers_stdio", "opencode_mcp"):
        data = _read_json_safe(config_path)
        key = "mcp" if fmt == "opencode_mcp" else "mcpServers"
        root = data.get(key)
        if isinstance(root, dict) and SERVER_NAME in root:
            if dry_run:
                print(f"  [dry-run] Would remove {SERVER_NAME} from {config_path}")
                return True
            _backup_file(config_path)
            del root[SERVER_NAME]
            _write_json_atomic(config_path, data)
            print(f"  [OK] Removed from {config_path}")
            return True
    elif fmt == "continue_mcp":
        data = _read_json_safe(config_path)
        servers = data.get("mcpServers")
        if isinstance(servers, list):
            before = len(servers)
            servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == SERVER_NAME)]
            if len(servers) < before:
                if dry_run:
                    print(f"  [dry-run] Would remove {SERVER_NAME} from {config_path}")
                    return True
                data["mcpServers"] = servers
                _backup_file(config_path)
                _write_json_atomic(config_path, data)
                print(f"  [OK] Removed from {config_path}")
                return True
    elif fmt == "zed_context_server":
        data = _read_json_safe(config_path)
        ctx = data.get("context_servers")
        if isinstance(ctx, dict) and SERVER_NAME in ctx:
            if dry_run:
                print(f"  [dry-run] Would remove {SERVER_NAME} from {config_path}")
                return True
            _backup_file(config_path)
            del ctx[SERVER_NAME]
            _write_json_atomic(config_path, data)
            print(f"  [OK] Removed from {config_path}")
            return True
    return False


def verify_registration(tool_name: str, tool_def: dict[str, Any]) -> bool:
    config_path = find_config_path(tool_def)
    if config_path is None or not config_path.exists():
        return False
    fmt = tool_def.get("config_format")
    data = _read_json_safe(config_path)
    if fmt == "opencode_mcp":
        root = data.get("mcp")
        return isinstance(root, dict) and SERVER_NAME in root
    if fmt == "mcpServers_stdio":
        root = data.get("mcpServers")
        return isinstance(root, dict) and SERVER_NAME in root
    if fmt == "continue_mcp":
        servers = data.get("mcpServers")
        return isinstance(servers, list) and any(isinstance(s, dict) and s.get("name") == SERVER_NAME for s in servers)
    if fmt == "zed_context_server":
        root = data.get("context_servers")
        return isinstance(root, dict) and SERVER_NAME in root
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Register ContextCore MCP server for local tools.")
    parser.add_argument("--tool", "-t", help="Single tool to register, e.g. claude-code, cline, cursor.")
    parser.add_argument("--all", "-a", action="store_true", help="Register all supported tools.")
    parser.add_argument("--list", "-l", action="store_true", help="List tools and detected config paths.")
    parser.add_argument("--verify", "-v", action="store_true", help="Verify existing registrations.")
    parser.add_argument("--unregister", action="store_true", help="Remove ContextCore from tool configs.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing files.")
    parser.add_argument("--python", help="Override Python executable path.")
    parser.add_argument("--mcp-script", help="Override mcp_server.py path.")
    args = parser.parse_args()

    tools = get_tool_definitions()

    if args.list:
        detected = set(detect_installed_tools(tools))
        print("Tool detection:\n")
        for name, spec in tools.items():
            cfg = find_config_path(spec)
            status = "detected" if name in detected else "not-found"
            print(f"- {name:14} {status:10} {cfg}")
        return 0

    if args.verify:
        print("Verification:\n")
        for name, spec in tools.items():
            ok = verify_registration(name, spec)
            print(f"- {name:14} {'registered' if ok else 'missing'}")
        return 0

    try:
        python_path = str(pathlib.Path(args.python).expanduser().resolve()) if args.python else resolve_python()
        mcp_script_path = str(pathlib.Path(args.mcp_script).expanduser().resolve()) if args.mcp_script else resolve_mcp_server()
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    if not pathlib.Path(python_path).exists():
        print(f"Error: Python not found at {python_path}")
        return 1
    if not pathlib.Path(mcp_script_path).exists():
        print(f"Error: mcp_server.py not found at {mcp_script_path}")
        return 1

    print("ContextCore MCP Registration")
    print("-" * 50)
    print(f"Python:     {python_path}")
    print(f"MCP server: {mcp_script_path}")
    print("-" * 50)

    if args.unregister:
        removed = 0
        for name, spec in tools.items():
            if unregister_tool(name, spec, dry_run=args.dry_run):
                removed += 1
        print(f"\nRemoved from {removed} tool config(s).")
        return 0

    if args.tool:
        tool_name = args.tool.strip().lower()
        if tool_name not in tools:
            print(f"Unknown tool: {tool_name}")
            print(f"Supported: {', '.join(sorted(tools.keys()))}")
            return 1
        target_tools = {tool_name: tools[tool_name]}
    elif args.all:
        target_tools = tools
    else:
        detected = detect_installed_tools(tools)
        if not detected:
            print("No known tool config files detected. Use --all to force registration.")
            return 0
        target_tools = {name: tools[name] for name in detected}

    if args.dry_run:
        print("[dry-run] No files will be modified.\n")

    success = 0
    failed = 0
    for name, spec in target_tools.items():
        print(f"{spec['display_name']}")
        ok = register_tool(name, spec, python_path, mcp_script_path, dry_run=args.dry_run)
        if ok:
            success += 1
        else:
            failed += 1
        print("")

    print("-" * 50)
    if args.dry_run:
        print(f"Dry run complete. {success} tool(s) would be updated.")
        return 0

    print(f"Registration complete. {success} succeeded, {failed} failed.")
    if success > 0:
        print("Next steps:")
        print("1. Restart registered tools.")
        print("2. Confirm backend health: contextcore status")
        print("3. In Claude Code, run /mcp and check contextcore is listed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
