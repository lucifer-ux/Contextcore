# video_search_implementation_v2/watcher.py
#
# Problem 6 — Watchdog filesystem watcher for video directories
# with a background indexing queue.
#
# Usage:
#   from video_search_implementation_v2.watcher import start_video_watcher, stop_video_watcher
#   start_video_watcher()   # call once at app startup
#   stop_video_watcher()    # call on shutdown

import os
import sys
import threading
import queue
import time
from pathlib import Path
from typing import Optional

# Ensure parent is on path for config import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}

# ── Indexing queue ────────────────────────────────────────────
_index_queue: queue.Queue = queue.Queue()
_worker_thread: Optional[threading.Thread] = None
_observer = None  # watchdog.Observer
_stop_event = threading.Event()


def _queue_worker():
    """
    Background worker that processes video indexing jobs one at a time.
    Respects a configurable concurrency limit (default: 1 — sequential).
    """
    from video_search_implementation_v2.video_index import scan_video_index

    while not _stop_event.is_set():
        try:
            job = _index_queue.get(timeout=2.0)
        except queue.Empty:
            continue

        action = job.get("action")
        path = job.get("path")

        if action == "index":
            print(f"🔄 Watcher: indexing {path}")
            try:
                # Index only the parent directory containing this file
                video_dir = Path(path).parent
                scan_video_index(video_dir)
            except Exception as e:
                print(f"⚠️ Watcher: indexing failed for {path}: {e}")

        elif action == "delete":
            print(f"🗑️ Watcher: removing index entries for {path}")
            try:
                _remove_video_from_index(path)
            except Exception as e:
                print(f"⚠️ Watcher: delete failed for {path}: {e}")

        _index_queue.task_done()


def _remove_video_from_index(video_path: str):
    """Remove all frame data for a deleted video from the DB."""
    from video_search_implementation_v2.video_index import _get_conn
    conn = _get_conn()
    try:
        row = conn.execute("SELECT id FROM videos WHERE path = ?", (video_path,)).fetchone()
        if row:
            video_id = row["id"]
            # Remove frame vectors
            old_frames = conn.execute(
                "SELECT id FROM frames WHERE video_id = ?", (video_id,)
            ).fetchall()
            for of in old_frames:
                try:
                    conn.execute("DELETE FROM frame_vectors WHERE rowid = ?", (of["id"],))
                except Exception:
                    pass
                try:
                    conn.execute("DELETE FROM frames_fts WHERE rowid = ?", (of["id"],))
                except Exception:
                    pass
            conn.execute("DELETE FROM frames WHERE video_id = ?", (video_id,))
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            conn.commit()
            print(f"🗑️ Removed {len(old_frames)} frames for {video_path}")
    except Exception as e:
        print(f"⚠️ Failed to remove video from index: {e}")
    finally:
        conn.close()


# ── Watchdog event handler ────────────────────────────────────

def _create_handler():
    """Create a watchdog event handler for video files."""
    from watchdog.events import FileSystemEventHandler

    class VideoEventHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            if Path(event.src_path).suffix.lower() in VIDEO_EXTS:
                # Small delay to let file finish writing
                time.sleep(1.0)
                _index_queue.put({"action": "index", "path": event.src_path})

        def on_modified(self, event):
            if event.is_directory:
                return
            if Path(event.src_path).suffix.lower() in VIDEO_EXTS:
                time.sleep(1.0)
                _index_queue.put({"action": "index", "path": event.src_path})

        def on_deleted(self, event):
            if event.is_directory:
                return
            if Path(event.src_path).suffix.lower() in VIDEO_EXTS:
                _index_queue.put({"action": "delete", "path": event.src_path})

    return VideoEventHandler()


# ── Public API ────────────────────────────────────────────────

def start_video_watcher():
    """
    Start watching all configured video directories.
    Creates a background worker thread for processing the index queue
    and a watchdog Observer for each configured directory.
    """
    global _worker_thread, _observer

    if _worker_thread is not None and _worker_thread.is_alive():
        print("⚠️ Video watcher already running")
        return

    from watchdog.observers import Observer
    from config import get_video_directories

    _stop_event.clear()

    # Start the queue worker
    _worker_thread = threading.Thread(target=_queue_worker, daemon=True, name="video-indexer")
    _worker_thread.start()

    # Start the filesystem observer
    _observer = Observer()
    handler = _create_handler()
    dirs = get_video_directories()

    for d in dirs:
        if d.is_dir():
            _observer.schedule(handler, str(d), recursive=True)
            print(f"👁️ Watching video directory: {d}")

    _observer.daemon = True
    _observer.start()
    print("✅ Video watcher started")


def stop_video_watcher():
    """Stop the filesystem watcher and queue worker."""
    global _observer, _worker_thread

    _stop_event.set()

    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None

    if _worker_thread is not None:
        _worker_thread.join(timeout=5)
        _worker_thread = None

    print("🛑 Video watcher stopped")
