from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from cli.paths import get_sdk_root
from cli.ui import console, error, header, info, success, warning

_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?$")


def _normalize_repo_slug(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    m = _GITHUB_REMOTE_RE.search(text)
    if m:
        return m.group("slug")
    return text.replace("https://github.com/", "").replace("github.com/", "").strip("/")


def _detect_repo_slug(repo_override: str | None) -> str:
    explicit = _normalize_repo_slug(repo_override)
    if explicit:
        return explicit

    env_repo = _normalize_repo_slug(os.getenv("CONTEXTCORE_REPORT_REPO"))
    if env_repo:
        return env_repo

    sdk_root = get_sdk_root()
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=str(sdk_root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        git_repo = _normalize_repo_slug(out)
        if git_repo:
            return git_repo
    except Exception:
        pass

    return "lucifer-ux/SearchEmbedSDK"


def _first_line_title(message: str) -> str:
    line = (message or "").strip().splitlines()[0] if message.strip() else "ContextCore issue report"
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > 90:
        line = line[:87].rstrip() + "..."
    if not line:
        line = "ContextCore issue report"
    return line


def _collect_env_snapshot() -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "cwd": str(Path.cwd()),
    }


def _build_issue_body(message: str, extra: dict[str, Any]) -> str:
    fenced = json.dumps(extra, indent=2)
    return (
        "## User Report\n"
        f"{message.strip()}\n\n"
        "## Environment\n"
        "```json\n"
        f"{fenced}\n"
        "```\n"
    )


def _create_issue_via_gh(repo_slug: str, title: str, body: str) -> str | None:
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        auth = subprocess.run(
            [gh, "auth", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
        )
        if auth.returncode != 0:
            return None
        create = subprocess.run(
            [gh, "issue", "create", "--repo", repo_slug, "--title", title, "--body", body],
            capture_output=True,
            text=True,
            check=False,
        )
        if create.returncode == 0:
            return (create.stdout or "").strip().splitlines()[-1].strip()
    except Exception:
        return None
    return None


def _create_issue_via_api(repo_slug: str, title: str, body: str) -> str | None:
    token = os.getenv("CONTEXTCORE_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return None
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{repo_slug}/issues",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            payload = resp.json()
            return str(payload.get("html_url", "")).strip() or None
    except Exception:
        return None
    return None


def _prefilled_issue_url(repo_slug: str, title: str, body: str) -> str:
    return (
        f"https://github.com/{repo_slug}/issues/new?"
        f"title={quote_plus(title)}&body={quote_plus(body)}"
    )


def run_report(message: str | None = None, repo: str | None = None, title: str | None = None) -> None:
    header()

    text = (message or "").strip()
    if not text:
        text = console.input("  Describe the issue: ").strip()
    if not text:
        error("Issue text is required.")
        return

    repo_slug = _detect_repo_slug(repo)
    issue_title = (title or "").strip() or _first_line_title(text)
    env_snapshot = _collect_env_snapshot()
    issue_body = _build_issue_body(text, env_snapshot)

    info(f"Target repo: [bold]{repo_slug}[/bold]")
    info("Creating GitHub issue...\n")

    issue_url = _create_issue_via_gh(repo_slug, issue_title, issue_body)
    if issue_url:
        success("Issue created via GitHub CLI.")
        console.print(f"  [bold]{issue_url}[/bold]")
        return

    issue_url = _create_issue_via_api(repo_slug, issue_title, issue_body)
    if issue_url:
        success("Issue created via GitHub API.")
        console.print(f"  [bold]{issue_url}[/bold]")
        return

    warning("Could not auto-create issue (missing GitHub auth).")
    console.print("  [dim]Use one of these auth options:[/dim]")
    console.print("  [dim]- Login with GitHub CLI: gh auth login[/dim]")
    console.print("  [dim]- Or set token env var: CONTEXTCORE_GITHUB_TOKEN[/dim]")
    console.print()
    fallback = _prefilled_issue_url(repo_slug, issue_title, issue_body)
    info("Open this prefilled issue URL:")
    console.print(f"  [bold]{fallback}[/bold]")
