from pathlib import Path

IGNORE_DIRS = {
    "thumbnails",
    ".radxa",
    ".git",
    "__pycache__",
}

THUMB_ROOT = Path("/mnt/storage/thumbnails")

def should_ignore(path: Path) -> bool:
    if THUMB_ROOT in path.parents:
        return True

    if path.stem.endswith("_thumbnail"):
        return True

    if path.name.startswith("."):
        return True

    return False