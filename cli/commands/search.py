# cli/commands/search.py

import os
import sys
import subprocess
import webbrowser
import requests
from pathlib import Path

import questionary
from cli.constants import DEFAULT_PORT
from cli.ui import console

API_BASE = f"http://127.0.0.1:{DEFAULT_PORT}"


def run_search():
    from cli.server import is_server_running, ensure_server

    ensure_server(port=DEFAULT_PORT, silent=True)
    if not is_server_running(DEFAULT_PORT):
        console.print("[red]Error:[/red] ContextCore server not running.")
        console.print("  Start it with: [bold]contextcore serve[/bold]")
        return

    while True:
        query = questionary.text(
            "Search (or 'q' to quit):",
            qmark=">",
        ).ask()

        if not query or query.strip().lower() in ("q", "quit", "exit"):
            break

        results = _search_api(query.strip())
        if not results:
            console.print("[yellow]No results found.[/yellow]")
            continue

        all_items = _display_results(results)

        if not all_items:
            continue

        choice = questionary.text(
            "Enter number to open (or 'n' new search, 'q' quit):",
            qmark=">",
        ).ask()

        if not choice:
            continue

        choice = choice.strip().lower()
        if choice in ("q", "quit", "exit"):
            break
        if choice in ("n", "new"):
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(all_items):
                _open_item(all_items[idx])
            else:
                console.print("[red]Invalid selection.[/red]")
        else:
            console.print("[red]Invalid input. Enter a number, 'n' for new search, or 'q' to quit.[/red]")

    console.print("[dim]Goodbye![/dim]")


def _search_api(query: str, top_k: int = 20) -> dict:
    try:
        r = requests.get(
            f"{API_BASE}/search",
            params={"query": query, "top_k": top_k, "modality": "all"},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
        else:
            console.print(f"[red]Search error:[/red] {r.status_code}")
    except requests.exceptions.ConnectionError:
        console.print(f"[red]Cannot connect to server at[/red] {API_BASE}")
    except Exception as e:
        console.print(f"[red]Search failed:[/red] {e}")
    return {}


def _display_results(results: dict) -> list:
    all_items = []
    skip_keys = {"query", "modality"}
    category_names = {
        "text": "Text",
        "image": "Images",
        "video": "Videos",
        "audio": "Audio",
    }

    for category, data in results.items():
        if category in skip_keys:
            continue

        if not isinstance(data, dict):
            continue

        items = data.get("results", [])
        if not items:
            continue

        items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)

        display_name = category_names.get(category, category.capitalize())
        console.print(f"\n[bold cyan]{display_name} ({len(items)})[/bold cyan]")

        for item in items[:20]:
            if category == "video":
                path = item.get("video_path", "")
            else:
                path = item.get("path", "")
            
            filename = item.get("filename", Path(path).name if path else "Unknown")
            score = item.get("score", 0)

            all_items.append({"path": path, "filename": filename, "category": category, "score": score})
            idx = len(all_items)

            console.print(f"  [bold]{idx}.[/bold] {filename}")
            console.print(f"      [dim]{path}[/dim]")
            console.print(f"      [dim]Score: {score:.2f}[/dim]")

    return all_items


def _open_item(item: dict):
    path = item.get("path", "")
    if not path:
        console.print("[red]No path found for this item.[/red]")
        return

    filepath = Path(path)
    if not filepath.exists():
        console.print(f"[red]File not found:[/red] {path}")
        return

    action = questionary.select(
        "Open file or folder?",
        choices=[
            "Open file",
            "Open containing folder",
        ],
    ).ask()

    try:
        if action == "Open file":
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=True)
            else:
                subprocess.run(["xdg-open", path], check=True)
            console.print(f"[green]Opened:[/green] {path}")
        elif action == "Open containing folder":
            folder = filepath.parent
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)], check=True)
            else:
                subprocess.run(["xdg-open", str(folder)], check=True)
            console.print(f"[green]Opened folder:[/green] {folder}")
    except Exception as e:
        console.print(f"[red]Failed to open:[/red] {e}")