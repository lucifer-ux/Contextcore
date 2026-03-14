from __future__ import annotations

import threading
from pathlib import Path

from faster_whisper import WhisperModel

from text_search_implementation_v2.db import get_file_mtime, upsert_file

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

_whisper_model = None
_whisper_lock = threading.Lock()


def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        print("Loading Whisper model...")
        _whisper_model = WhisperModel("small.en", device="cpu", compute_type="int8")
    return _whisper_model


def prewarm_whisper() -> tuple[bool, str | None]:
    try:
        get_whisper()
        return True, None
    except Exception as exc:
        return False, str(exc)


def transcribe_audio(path: Path):
    model = get_whisper()
    segments, _ = model.transcribe(str(path))
    return " ".join(seg.text.strip() for seg in segments if seg.text.strip())


def scan_audio_index(audio_root: Path):
    total_new = 0

    for path in audio_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
            continue

        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue

        existing_mtime = get_file_mtime(str(path))
        if existing_mtime is not None and abs(existing_mtime - mtime) < 0.001:
            continue

        print("Transcribing:", path)
        try:
            transcript = transcribe_audio(path)
        except Exception as exc:
            print("Transcription failed:", exc)
            continue

        if not transcript:
            continue

        upsert_file(str(path), path.name, "audio", mtime, transcript)
        total_new += 1

    return {"status": "ok", "new_audio_indexed": total_new}
