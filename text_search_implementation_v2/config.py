# text_search_implementation_v2/config.py
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from config import get_organized_root
BASE_DIR = get_organized_root()
TEXT_FOLDERS = ["docs", "spreadsheets", "code"]
