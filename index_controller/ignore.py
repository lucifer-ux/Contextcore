from pathlib import Path

IGNORE_DIRS = {
    "thumbnails",
    ".radxa",
    ".git",
    "__pycache__",
}

import sys
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from config import get_organized_root

THUMB_ROOT = get_organized_root() / ".thumbnails"

def should_ignore(path: Path) -> bool:
    if THUMB_ROOT in path.parents:
        return True

    if path.stem.endswith("_thumbnail"):
        return True

    if path.name.startswith("."):
        return True

    return False