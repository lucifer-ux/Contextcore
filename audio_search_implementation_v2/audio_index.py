# audio_search_implementation_v2/audio_index.py

import sqlite3
import threading
from pathlib import Path
from faster_whisper import WhisperModel
from text_search_implementation_v2.db import upsert_file, get_file_mtime
from text_search_implementation_v2.config import BASE_DIR

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

_whisper_model = None
_whisper_lock = threading.Lock()

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        print("🎧 Loading Whisper model...")
        _whisper_model = WhisperModel("small.en", device="cpu", compute_type="int8")
    return _whisper_model


def transcribe_audio(path: Path):
    model = get_whisper()
    segments, _ = model.transcribe(str(path))
    text = []
    for seg in segments:
        text.append(seg.text.strip())
    return " ".join(text)


def scan_audio_index(audio_root: Path):
    total_new = 0

    for p in audio_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in AUDIO_EXTS:
            continue

        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue


        existing_mtime = get_file_mtime(str(p))
        if existing_mtime is not None:
            if abs(existing_mtime - mtime) < 0.001:
                continue


        print("🎧 Transcribing:", p)
        try:
            transcript = transcribe_audio(p)
        except Exception as e:
            print("⚠️ Transcription failed:", e)
            continue

        if not transcript:
            continue

        upsert_file(str(p), p.name, "audio", mtime, transcript)
        total_new += 1

    return {"status": "ok", "new_audio_indexed": total_new}
