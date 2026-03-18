from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from cli.constants import DEFAULT_PORT
from cli.paths import get_default_config, get_sdk_root

CONTEXTCORE_HOME = Path.home() / ".contextcore"
INDEX_LOCK_PATH = CONTEXTCORE_HOME / "index.lock"
INDEX_STATE_PATH = CONTEXTCORE_HOME / "index_state.json"
AUTOSTART_META_PATH = CONTEXTCORE_HOME / "autostart.json"
WINDOWS_TASK_NAME = "ContextCoreServer"
MACOS_LAUNCH_AGENT_LABEL = "ai.contextcore.server"
MACOS_LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LAUNCH_AGENT_LABEL}.plist"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_home() -> None:
    CONTEXTCORE_HOME.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> bool:
    _ensure_home()
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except PermissionError:
        # Keep runtime operational even if local state file permissions are broken.
        return False
    except OSError:
        return False


def is_pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def is_contextcore_healthy(port: int = DEFAULT_PORT) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return resp.status == 200 and '"status"' in raw and '"ok"' in raw
    except URLError:
        return False
    except Exception:
        return False


def get_port_usage(port: int = DEFAULT_PORT) -> dict[str, Any]:
    info: dict[str, Any] = {
        "port": port,
        "in_use": False,
        "is_contextcore": False,
        "pid": None,
        "process_name": None,
        "command_line": None,
    }
    if is_contextcore_healthy(port):
        info["in_use"] = True
        info["is_contextcore"] = True
        return info

    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in output.splitlines():
                parts = [p for p in line.split() if p]
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                    pid = int(parts[4])
                    info["in_use"] = True
                    info["pid"] = pid
                    break
            if info["pid"]:
                task = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {info['pid']}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                row = task.stdout.strip().strip('"')
                if row:
                    pieces = [p.strip('"') for p in row.split('","')]
                    if pieces:
                        info["process_name"] = pieces[0]
        else:
            output = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [ln for ln in output.stdout.splitlines() if ln.strip()]
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2:
                    info["in_use"] = True
                    info["process_name"] = parts[0]
                    info["pid"] = int(parts[1])
        if info["pid"] and not info["process_name"] and platform.system() != "Windows":
            ps = subprocess.run(
                ["ps", "-p", str(info["pid"]), "-o", "comm=", "-o", "args="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [ln.strip() for ln in ps.stdout.splitlines() if ln.strip()]
            if lines:
                first = lines[0].split(maxsplit=1)
                info["process_name"] = first[0]
                info["command_line"] = first[1] if len(first) > 1 else first[0]
    except Exception:
        pass
    return info


def _lock_payload(source: str, targets: list[str], modalities: list[str]) -> dict[str, Any]:
    return {
        "active": True,
        "owner_pid": os.getpid(),
        "source": source,
        "targets": targets,
        "modalities": modalities,
        "started_at": _now_iso(),
        "last_updated_at": _now_iso(),
        "progress": None,
        "result": None,
        "error": None,
    }


def read_index_state() -> dict[str, Any]:
    return _read_json(INDEX_STATE_PATH)


def update_index_state(**updates: Any) -> dict[str, Any]:
    state = read_index_state()
    state.update(updates)
    state["last_updated_at"] = _now_iso()
    _write_json(INDEX_STATE_PATH, state)
    return state


def acquire_index_lock(source: str, targets: list[str], modalities: list[str]) -> tuple[bool, dict[str, Any]]:
    _ensure_home()
    state = read_index_state()
    if INDEX_LOCK_PATH.exists():
        owner_pid = state.get("owner_pid")
        if is_pid_running(int(owner_pid) if owner_pid else 0):
            return False, state
        INDEX_LOCK_PATH.unlink(missing_ok=True)
        state["stale_lock_recovered_at"] = _now_iso()
    payload = _lock_payload(source, targets, modalities)
    try:
        fd = os.open(str(INDEX_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except FileExistsError:
        state = read_index_state()
        return False, state
    _write_json(INDEX_STATE_PATH, payload)
    return True, payload


def release_index_lock(result: str = "completed", error: str | None = None) -> None:
    state = read_index_state()
    state["active"] = False
    state["completed_at"] = _now_iso()
    state["result"] = result
    state["error"] = error
    _write_json(INDEX_STATE_PATH, state)
    INDEX_LOCK_PATH.unlink(missing_ok=True)


def index_lock_active() -> tuple[bool, dict[str, Any]]:
    state = read_index_state()
    if not INDEX_LOCK_PATH.exists():
        return False, state
    owner_pid = state.get("owner_pid")
    if is_pid_running(int(owner_pid) if owner_pid else 0):
        return True, state
    INDEX_LOCK_PATH.unlink(missing_ok=True)
    state["active"] = False
    state["stale_lock_recovered_at"] = _now_iso()
    _write_json(INDEX_STATE_PATH, state)
    return False, state


def build_background_server_command(port: int = DEFAULT_PORT) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "unimain:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]


def install_autostart(port: int = DEFAULT_PORT) -> tuple[bool, str]:
    _ensure_home()
    sdk_root = get_sdk_root()
    config_path = get_default_config()
    system = platform.system()
    try:
        if system == "Windows":
            script_path = CONTEXTCORE_HOME / "start_contextcore.ps1"
            command = (
                f"$env:CONTEXTCORE_CONFIG='{config_path}'; "
                f"Set-Location '{sdk_root}'; "
                f"& '{sys.executable}' -m uvicorn unimain:app --host 127.0.0.1 --port {port} --log-level warning"
            )
            script_path.write_text(command + "\n", encoding="utf-8")
            task_command = (
                f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script_path}"'
            )
            result = subprocess.run(
                ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", WINDOWS_TASK_NAME, "/TR", task_command],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                return False, result.stderr.strip() or result.stdout.strip() or "schtasks create failed"
            meta = {
                "installed": True,
                "target": "windows_task_scheduler",
                "task_name": WINDOWS_TASK_NAME,
                "script_path": str(script_path),
                "command": task_command,
                "port": port,
            }
        elif system == "Darwin":
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{MACOS_LAUNCH_AGENT_LABEL}</string>
  <key>WorkingDirectory</key><string>{sdk_root}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>unimain:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>{port}</string>
    <string>--log-level</string>
    <string>warning</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CONTEXTCORE_CONFIG</key><string>{config_path}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""
            MACOS_LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            MACOS_LAUNCH_AGENT_PATH.write_text(plist, encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(MACOS_LAUNCH_AGENT_PATH)], capture_output=True, timeout=10)
            result = subprocess.run(["launchctl", "load", str(MACOS_LAUNCH_AGENT_PATH)], capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                return False, result.stderr.strip() or result.stdout.strip() or "launchctl load failed"
            meta = {
                "installed": True,
                "target": "macos_launch_agent",
                "label": MACOS_LAUNCH_AGENT_LABEL,
                "plist_path": str(MACOS_LAUNCH_AGENT_PATH),
                "port": port,
            }
        else:
            return False, "per-user autostart is not implemented for this platform yet"
        meta["installed_at"] = _now_iso()
        _write_json(AUTOSTART_META_PATH, meta)
        return True, "autostart installed"
    except Exception as exc:
        return False, str(exc)


def autostart_status() -> dict[str, Any]:
    meta = _read_json(AUTOSTART_META_PATH)
    system = platform.system()
    installed = False
    if system == "Windows":
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        installed = result.returncode == 0
    elif system == "Darwin":
        installed = MACOS_LAUNCH_AGENT_PATH.exists()
    meta.setdefault("installed", installed)
    meta["installed"] = installed
    meta.setdefault("target", "not_configured")
    return meta


def stop_pid(pid: int) -> bool:
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False
