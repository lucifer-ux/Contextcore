from pathlib import Path
import subprocess
from PIL import Image

import sys
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from config import get_organized_root

STORAGE_ROOT = get_organized_root()
THUMB_ROOT = STORAGE_ROOT / ".thumbnails"

IMAGE_THUMB_DIR = THUMB_ROOT / "images"
VIDEO_THUMB_DIR = THUMB_ROOT / "video"
DOCS_THUMB_DIR  = THUMB_ROOT / "docs"

for d in (IMAGE_THUMB_DIR, VIDEO_THUMB_DIR, DOCS_THUMB_DIR):
    d.mkdir(parents=True, exist_ok=True)

THUMB_SIZE = (320, 320)

# --------------------------------------------------
# Path helpers
# --------------------------------------------------
def thumbnail_path(file_path: Path, category: str) -> Path:
    """
    demo.mp4 -> thumbnails/video/demo_thumbnail.jpg
    """
    name = f"{file_path.stem}_thumbnail.jpg"

    if category == "image":
        return IMAGE_THUMB_DIR / name
    if category == "video":
        return VIDEO_THUMB_DIR / name
    if category == "docs":
        return DOCS_THUMB_DIR / name

    raise ValueError(f"Unknown category: {category}")


def thumbnail_exists(file_path: Path, category: str) -> bool:
    return thumbnail_path(file_path, category).exists()

# --------------------------------------------------
# Generators
# --------------------------------------------------
def _generate_image_thumbnail(src: Path, dest: Path):
    with Image.open(src) as img:
        img.thumbnail(THUMB_SIZE)
        img.convert("RGB").save(dest, "JPEG", quality=85)


def _generate_video_thumbnail(src: Path, dest: Path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(src),
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _generate_pdf_thumbnail(src: Path, dest: Path):
    subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-f", "1",
            "-l", "1",
            str(src),
            str(dest.with_suffix(""))
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

# --------------------------------------------------
# Public entry (INDEX CALLS THIS)
# --------------------------------------------------
def ensure_thumbnail(file_path: Path, category: str):
    """
    Called during indexing.
    Idempotent.
    """
    dest = thumbnail_path(file_path, category)

    if dest.exists():
        return

    try:
        if category == "image":
            _generate_image_thumbnail(file_path, dest)
        elif category == "video":
            _generate_video_thumbnail(file_path, dest)
        elif category == "docs" and file_path.suffix.lower() == ".pdf":
            _generate_pdf_thumbnail(file_path, dest)
    except Exception as e:
        print(f"⚠️ Thumbnail generation failed for {file_path}: {e}")

def read_thumbnail(file_path: Path, category: str) -> bytes | None:
    thumb = thumbnail_path(file_path, category)
    if not thumb.exists():
        return None
    return thumb.read_bytes()
