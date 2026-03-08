# text_search_implementation_v2/index_worker.py
import argparse
from pathlib import Path
from text_search_implementation_v2.db import init_db, upsert_file, get_file_mtime
from text_search_implementation_v2.extract import extract_text
from text_search_implementation_v2.config import BASE_DIR, TEXT_FOLDERS


SUPPORTED_EXT = {
    "txt",
    "md",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "csv",
    "xlsx",
    "xls",
    "json",
    "xml",
    "rtf",
    "ods",
}


def index_one_file(p: Path):
    try:
        current_mtime = p.stat().st_mtime
    except Exception:
        return False

    # 🔎 Check existing DB record before extracting text
    existing_mtime = get_file_mtime(str(p))
    if existing_mtime is not None:
        # skip unchanged file
        if abs(existing_mtime - current_mtime) < 0.001:
            return False

    # Only extract if new or modified
    content = extract_text(p)
    if not content:
        return False

    upsert_file(str(p), p.name, p.parent.name, current_mtime, content)
    return True


def full_scan():
    init_db()
    total = 0
    skipped = 0

    for folder in TEXT_FOLDERS:
        folder_path = BASE_DIR / folder
        if not folder_path.exists():
            continue

        for path in folder_path.rglob("*"):
            if not path.is_file():
                continue

            if path.suffix.lower().lstrip(".") not in SUPPORTED_EXT:
                continue

            if index_one_file(path):
                total += 1
            else:
                skipped += 1

    print(f"Indexed files: {total}, Skipped unchanged: {skipped}")


def run_scan():
    full_scan()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Single file to index")
    parser.add_argument("--scan", action="store_true", help="Do a full startup scan")
    args = parser.parse_args()

    init_db()

    if args.file:
        p = Path(args.file)
        print("Indexing:", p)
        ok = index_one_file(p)
        print("Indexed", ok)

    elif args.scan:
        full_scan()

    else:
        print("Nothing to do. Use --file or --scan")


if __name__ == "__main__":
    main()
