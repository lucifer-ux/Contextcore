# audio_search_implementation_v2/scanner.py

from pathlib import Path
from faster_whisper import WhisperModel
from text_search_implementation_v2.db import upsert_file, get_file_mtime

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

def run_audio_scan(audio_root: Path):
    print("🎧 Loading Whisper model...")
    model = WhisperModel("small.en", device="cpu", compute_type="int8")

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
            segments, _ = model.transcribe(str(p))
            transcript = " ".join(seg.text.strip() for seg in segments)
        except Exception as e:
            print("⚠️ Transcription failed:", e)
            continue

        if not transcript:
            continue

        upsert_file(str(p), p.name, "audio", mtime, transcript)
        total_new += 1

    print("🎧 Audio indexing complete. New files:", total_new)
    return total_new
