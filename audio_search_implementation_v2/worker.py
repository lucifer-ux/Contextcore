# audio_search_implementation_v2/worker.py

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from pathlib import Path
from audio_search_implementation_v2.scanner import run_audio_scan
from config import get_audio_directories

if __name__ == "__main__":
    audio_dirs = get_audio_directories()
    print("🚀 Audio worker started")
    total = 0
    for audio_root in audio_dirs:
        if audio_root.is_dir():
            total += run_audio_scan(audio_root)
    print("🚀 Audio worker exiting. Indexed:", total)