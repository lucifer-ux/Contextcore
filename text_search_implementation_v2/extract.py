# text_search_implementation_v2/extract.py

from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET
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
            # Prefer system pdftotext when available; fall back to pure-Python reader.
            try:
                return subprocess.check_output(
                    ["pdftotext", str(path), "-"],
                    stderr=subprocess.DEVNULL,
                ).decode(errors="ignore")
            except Exception:
                try:
                    from pypdf import PdfReader

                    reader = PdfReader(str(path))
                    pages = [(p.extract_text() or "") for p in reader.pages]
                    return "\n".join(pages).strip()
                except Exception:
                    return ""

        if ext == ".pptx":
            # Pure-Python extraction from PPTX slide XML.
            try:
                texts = []
                with zipfile.ZipFile(path, "r") as zf:
                    slide_names = sorted(
                        n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                    )
                    for name in slide_names:
                        xml_data = zf.read(name)
                        root = ET.fromstring(xml_data)
                        for node in root.iter():
                            if node.tag.endswith("}t") and node.text:
                                texts.append(node.text)
                return "\n".join(texts).strip()
            except Exception:
                # Last-resort fallback through pandoc if installed.
                try:
                    return subprocess.check_output(
                        ["pandoc", str(path), "-t", "plain"],
                        stderr=subprocess.DEVNULL,
                    ).decode(errors="ignore")
                except Exception:
                    return ""

        if ext in {".doc", ".docx", ".ppt", ".rtf"}:
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
