# image_search_implementation_v2/ocr.py
from pathlib import Path
from PIL import Image
import shutil
import subprocess
import sys

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except Exception:
    TESSERACT_AVAILABLE = False

def extract_ocr_from_image(path: Path) -> str:
    ext = path.suffix.lower()
    # for PDFs, use pdftotext if available
    if ext == ".pdf":
        try:
            out = subprocess.check_output(["pdftotext", str(path), "-"], stderr=subprocess.DEVNULL)
            return out.decode(errors="ignore")
        except Exception:
            return ""
    # for images, use pytesseract if installed
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        img = Image.open(path).convert("RGB")
        return pytesseract.image_to_string(img)
    except Exception:
        return ""
