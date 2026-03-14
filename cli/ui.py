from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "dim cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "dim": "dim",
        "header": "bold white",
    }
)

console = Console(theme=_THEME)

_ENCODING = (getattr(sys.stdout, "encoding", None) or "").lower()
_UNICODE_OK = "utf" in _ENCODING or _ENCODING in {"cp65001"}
_SYM_SUCCESS = "✓" if _UNICODE_OK else "[OK]"
_SYM_WARNING = "⚠" if _UNICODE_OK else "[!]"
_SYM_ERROR = "✗" if _UNICODE_OK else "[X]"
_SYM_INFO = "•" if _UNICODE_OK else "-"
_TITLE_SUFFIX = " ✦" if _UNICODE_OK else ""


def header(title: str = f"ContextCore{_TITLE_SUFFIX}") -> None:
    console.print()
    console.print(f"[bold cyan]{'-' * 32} {title} {'-' * 32}[/bold cyan]")
    console.print()


def section(title: str) -> None:
    console.print()
    console.print(f"[bold]{title}[/bold]")
    console.print(f"[dim]{'-' * 78}[/dim]")


def success(msg: str) -> None:
    console.print(f"  [success]{_SYM_SUCCESS}[/success] {msg}")


def warning(msg: str) -> None:
    console.print(f"  [warning]{_SYM_WARNING}[/warning] {msg}")


def error(msg: str) -> None:
    console.print(f"  [error]{_SYM_ERROR}[/error] {msg}")


def info(msg: str) -> None:
    console.print(f"  [info]{_SYM_INFO}[/info] {msg}")


def hint(label: str, cmd: str) -> None:
    console.print(f"\n    Fix: [bold yellow]{cmd}[/bold yellow]  ({label})\n")


def done_panel(lines: list[str]) -> None:
    body = "\n".join(f"  {line}" for line in lines)
    panel_title = f"[bold green]Setup complete{_TITLE_SUFFIX}[/bold green]"
    console.print()
    console.print(Panel(body, title=panel_title, border_style="green", padding=(1, 2)))
    console.print()
