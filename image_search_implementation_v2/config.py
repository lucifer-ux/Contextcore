# image_search_implementation_v2/config.py
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from config import get_organized_root, get_image_directory

BASE_DIR = get_organized_root()
try:
    IMAGE_FOLDER = get_image_directory().relative_to(BASE_DIR)
except ValueError:
    IMAGE_FOLDER = get_image_directory()

DATA_DIR = Path(__file__).parent / "storage"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "images_v2.db"

# Qdrant config - adjust if your qdrant server binds elsewhere
QDRANT_URL = "http://127.0.0.1:6333"
QDRANT_COLLECTION = "images_v2"

# Embedding model name (CLIP). This model will be loaded only in workers.
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"  # reliable baseline; can swap later
VECTOR_DIM = 512

# indexing / search tunables
ANN_TOPK = 50
FTS_TOPK = 50
UNION_LIMIT = 100

# fuzzy parameters
FUZZY_FILENAME_THRESHOLD = 70
