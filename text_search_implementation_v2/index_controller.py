# text_search_implementation_v2/index_controller.py

import subprocess
import sys
import platform
from pathlib import Path
from text_search_implementation_v2.config import BASE_DIR, TEXT_FOLDERS

def _get_popen_kwargs():
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kwargs

def index_single_file(path: Path):
    subprocess.Popen([
        sys.executable,
        "-m",
        "text_search_implementation_v2.index_worker",
        "--file",
        str(path)
    ], **_get_popen_kwargs())

def full_scan():
    subprocess.Popen([
        sys.executable,
        "-m",
        "text_search_implementation_v2.index_worker",
        "--scan"
    ], **_get_popen_kwargs())
