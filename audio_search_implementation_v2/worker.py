# audio_search_implementation_v2/worker.py

from pathlib import Path
from audio_search_implementation_v2.scanner import run_audio_scan

if __name__ == "__main__":
    audio_root = Path("/mnt/storage/organized_files/audio")
    print("🚀 Audio worker started")
    count = run_audio_scan(audio_root)
    print("🚀 Audio worker exiting. Indexed:", count)