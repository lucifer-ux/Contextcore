# image_search_implementation_v2/vector_store.py
from qdrant_client import QdrantClient
from qdrant_client.http import models as qtypes
from .config import QDRANT_URL, QDRANT_COLLECTION, VECTOR_DIM
import time

_client = None
_available = None

def get_client():
    global _client, _available
    if _client is None:
        try:
            _client = QdrantClient(url=QDRANT_URL)
            _available = True
        except Exception as e:
            print("Qdrant client init failed:", e)
            _available = False
            _client = None
    return _client

def qdrant_available():
    global _available
    if _available is None:
        get_client()
    return bool(_available)

def ensure_collection():
    if not qdrant_available():
        return False
    client = get_client()
    try:
        collections = [c.name for c in client.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            client.recreate_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qtypes.VectorParams(size=VECTOR_DIM, distance=qtypes.Distance.COSINE),
            )
        return True
    except Exception as e:
        print("ensure_collection failed:", e)
        return False

def upsert_vectors(points: list[dict], batch_size=64):
    """
    points: list of {"id": int, "vector": numpy.ndarray or list, "payload": dict}
    """
    if not qdrant_available():
        return False
    client = get_client()
    try:
        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            formatted = [
                {"id": p["id"], "vector": p["vector"].tolist() if hasattr(p["vector"], "tolist") else p["vector"], "payload": p.get("payload", {})}
                for p in batch
            ]
            client.upsert(collection_name=QDRANT_COLLECTION, points=formatted)
        return True
    except Exception as e:
        print("upsert_vectors failed:", e)
        return False

def search_vectors(query_vector, top_k=50):
    if not qdrant_available():
        return []
    client = get_client()
    try:
        hits = client.search(collection_name=QDRANT_COLLECTION, query_vector=query_vector.tolist(), limit=top_k, with_payload=True)
        # hits: list of ScoredPoint
        # normalize to list of dicts
        results = []
        for h in hits:
            payload = h.payload or {}
            results.append({
                "id": int(h.id),
                "score": float(h.score),
                "payload": payload
            })
        return results
    except Exception as e:
        print("search_vectors failed:", e)
        return []
