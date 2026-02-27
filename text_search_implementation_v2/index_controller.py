# text_search_implementation_v2/index_controller.py

import subprocess
from pathlib import Path
from text_search_implementation_v2.config import BASE_DIR, TEXT_FOLDERS

PYTHON_BIN = "/home/radxa/radxa-search/venv/bin/python"

def index_single_file(path: Path):
    subprocess.Popen([
        PYTHON_BIN,
        "-m",
        "text_search_implementation_v2.index_worker",
        "--file",
        str(path)
    ])

def full_scan():
    subprocess.Popen([
        PYTHON_BIN,
        "-m",
        "text_search_implementation_v2.index_worker",
        "--scan"
    ])
