# image_search_implementation_v2/main.py
from fastapi import FastAPI, Query, HTTPException
from .db import init_db
from .search import search as image_search
from .index_worker import index_file, full_scan
import uvicorn

app = FastAPI(title="Image Search V2")

@app.on_event("startup")
def startup():
    init_db()
    print("image-search-v2 ready")

@app.get("/health")
def health():
    return {"status": "ok", "service": "image-search-v2"}

@app.get("/search")
def api_search(q: str = Query(..., alias="query"), top_k: int = Query(20, ge=1, le=100)):
    return {"query": q, "results": image_search(q, top_k=top_k)}

@app.post("/index/scan")
def api_scan():
    # spawn worker as separate process in production; for now just call full_scan (blocking)
    # In dev you can use: python -m image_search_implementation_v2.index_worker --scan
    from threading import Thread
    Thread(target=full_scan, daemon=True).start()
    return {"status": "scan_started"}

@app.post("/index/file")
def api_index_file(path: str):
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="file not found")
    # spawn worker process in prod; for quick dev call index_file
    from threading import Thread
    Thread(target=index_file, args=(p,), daemon=True).start()
    return {"status": "index_started", "file": path}

if __name__ == "__main__":
    uvicorn.run("image_search_implementation_v2.main:app", host="0.0.0.0", port=8001, reload=False)
