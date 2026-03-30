from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cli.paths import get_default_config, get_sdk_root
from cli.ui import console, error, header, info, success, warning


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _print_git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    message = (result.stderr or result.stdout or "").strip() or "unknown git error"
    error(f"{prefix}: {message}")


def run_update(restart_server: bool = True) -> None:
    header()

    if shutil.which("git") is None:
        error("Git is not installed or not available on PATH.")
        return

    config_path = get_default_config()
    if not config_path.exists():
        error("ContextCore is not initialized on this machine yet.")
        console.print("  [dim]Run:[/dim] [bold]contextcore init[/bold]")
        return

    sdk_root = get_sdk_root().expanduser().resolve()
    if not sdk_root.exists() or not sdk_root.is_dir():
        error(f"Configured sdk_root does not exist: {sdk_root}")
        console.print(f"  [dim]Check:[/dim] [bold]{config_path}[/bold]")
        return

    info(f"Using sdk_root: [bold]{sdk_root}[/bold]")

    in_repo = _run_git(["rev-parse", "--is-inside-work-tree"], sdk_root, check=False)
    if in_repo.returncode != 0:
        error("Configured sdk_root is not a git repository.")
        console.print(f"  [dim]Path:[/dim] [bold]{sdk_root}[/bold]")
        return

    remote = _run_git(["remote", "get-url", "origin"], sdk_root, check=False)
    if remote.returncode != 0 or not (remote.stdout or "").strip():
        error("No git remote named 'origin' was found for this sdk_root.")
        return

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], sdk_root, check=False)
    current_branch = (branch.stdout or "").strip() if branch.returncode == 0 else ""
    if current_branch and current_branch != "HEAD":
        info(f"Current branch: [bold]{current_branch}[/bold]")

    dirty = _run_git(["status", "--porcelain"], sdk_root, check=False)
    if dirty.returncode != 0:
        _print_git_error("Could not read git status", dirty)
        return
    if (dirty.stdout or "").strip():
        warning("Local uncommitted changes detected. Skipping pull to avoid merge conflicts.")
        console.print("  [dim]Commit or stash your changes, then rerun:[/dim] [bold]contextcore update[/bold]")
        return

    before = _run_git(["rev-parse", "--short", "HEAD"], sdk_root, check=False)
    before_sha = (before.stdout or "").strip() if before.returncode == 0 else "unknown"

    info("Fetching latest changes from remote...")
    fetched = _run_git(["fetch", "--all", "--prune"], sdk_root, check=False)
    if fetched.returncode != 0:
        _print_git_error("Fetch failed", fetched)
        return

    info("Pulling latest commits (fast-forward only)...")
    pulled = _run_git(["pull", "--ff-only"], sdk_root, check=False)
    if pulled.returncode != 0:
        _print_git_error("Update failed", pulled)
        if "no tracking information" in ((pulled.stderr or "") + (pulled.stdout or "")).lower():
            console.print("  [dim]Set upstream once, then retry. Example:[/dim]")
            console.print("  [dim]git branch --set-upstream-to origin/main[/dim]")
        return

    after = _run_git(["rev-parse", "--short", "HEAD"], sdk_root, check=False)
    after_sha = (after.stdout or "").strip() if after.returncode == 0 else "unknown"

    if before_sha == after_sha:
        success("ContextCore is already up to date.")
    else:
        success(f"ContextCore updated: [bold]{before_sha}[/bold] -> [bold]{after_sha}[/bold]")
        changelog = _run_git(["log", "--oneline", f"{before_sha}..{after_sha}"], sdk_root, check=False)
        lines = [ln for ln in (changelog.stdout or "").splitlines() if ln.strip()]
        if lines:
            console.print("  [dim]New commits:[/dim]")
            for ln in lines[:10]:
                console.print(f"  [dim]- {ln}[/dim]")

    if not restart_server:
        return

    try:
        from cli.server import ensure_server, is_server_running
    except Exception as exc:
        warning(f"Update succeeded, but could not load server manager: {exc}")
        console.print("  [dim]Restart manually:[/dim] [bold]contextcore restart[/bold]")
        return

    if not is_server_running():
        return

    info("Restarting background server to apply updates...")
    if ensure_server(silent=True, force_restart=True):
        success("Background server restarted.")
    else:
        warning("Update succeeded, but automatic server restart failed.")
        console.print("  [dim]Restart manually:[/dim] [bold]contextcore restart[/bold]")
