from __future__ import annotations

import os
import platform


def _merge_path_values(values: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        for entry in value.split(os.pathsep):
            cleaned = entry.strip()
            if not cleaned:
                continue
            key = cleaned.lower() if platform.system() == "Windows" else cleaned
            if key in seen:
                continue
            seen.add(key)
            ordered.append(cleaned)
    return os.pathsep.join(ordered)


def get_refreshed_path() -> str:
    current = os.environ.get("PATH", "")
    if platform.system() != "Windows":
        return current

    try:
        import winreg

        machine_path = ""
        user_path = ""

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as key:
            machine_path = str(winreg.QueryValueEx(key, "Path")[0] or "")

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path = str(winreg.QueryValueEx(key, "Path")[0] or "")

        return _merge_path_values([current, user_path, machine_path])
    except Exception:
        return current


def refresh_process_path() -> str:
    refreshed = get_refreshed_path()
    os.environ["PATH"] = refreshed
    return refreshed


def build_runtime_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = get_refreshed_path()
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env
