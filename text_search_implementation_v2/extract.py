# text_search_implementation_v2/extract.py

from pathlib import Path
import subprocess
import pandas as pd

ALLOWED_EXTENSIONS = {
    ".txt",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".ods",
    ".csv",
    ".rtf",
}

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        return ""

    try:
        if ext == ".txt":
            return path.read_text(errors="ignore")

        if ext == ".pdf":
            return subprocess.check_output(
                ["pdftotext", str(path), "-"],
                stderr=subprocess.DEVNULL,
            ).decode(errors="ignore")

        if ext in {".doc", ".docx", ".ppt", ".pptx", ".rtf"}:
            return subprocess.check_output(
                ["pandoc", str(path), "-t", "plain"],
                stderr=subprocess.DEVNULL,
            ).decode(errors="ignore")

        if ext == ".csv":
            return pd.read_csv(path).astype(str).to_string()

        if ext in {".xls", ".xlsx", ".ods"}:
            dfs = pd.read_excel(path, sheet_name=None)
            return "\n".join(
                df.astype(str).to_string() for df in dfs.values()
            )

    except Exception:
        return ""

    return ""
