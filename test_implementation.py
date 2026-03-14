"""
test_implementation.py — Verify all the changes in a step-by-step way.

Run:  python test_implementation.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0
skipped = 0

def test(name, fn):
    global passed, failed, skipped
    try:
        result = fn()
        if result == "SKIP":
            print(f"  ⏭️  {name} — SKIPPED (dependency not available)")
            skipped += 1
        else:
            print(f"  ✅ {name}")
            passed += 1
    except Exception as e:
        print(f"  ❌ {name} — {e}")
        failed += 1


# ═══════════════════════════════════════════════════════════════
# STEP 1 — Config module
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 1: Config module")

def test_config_import():
    from config import (
        get_video_directories, get_audio_directories,
        get_image_directory, get_organized_root, get_dedup_threshold,
        reload_config,
    )
    assert callable(get_video_directories)
    assert callable(get_audio_directories)

test("config.py imports correctly", test_config_import)

def test_config_returns_paths():
    from config import get_video_directories, get_audio_directories, get_image_directory
    from pathlib import Path
    vids = get_video_directories()
    assert isinstance(vids, list) and all(isinstance(p, Path) for p in vids)
    auds = get_audio_directories()
    assert isinstance(auds, list)
    img = get_image_directory()
    assert isinstance(img, Path)

test("config returns valid Path objects", test_config_returns_paths)

def test_dedup_threshold():
    from config import get_dedup_threshold
    t = get_dedup_threshold()
    assert 0.0 < t < 1.0, f"threshold {t} out of range"
    assert t == 0.85, f"default should be 0.85, got {t}"

test("dedup threshold defaults to 0.85", test_dedup_threshold)


# ═══════════════════════════════════════════════════════════════
# STEP 2 — No hardcoded paths in unimain.py
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 2: No hardcoded paths")

def test_no_hardcoded_paths():
    with open("unimain.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert '/mnt/storage/organized_files/video' not in content, \
        "Hardcoded video path still present!"
    assert '/mnt/storage/organized_files/audio' not in content, \
        "Hardcoded audio path still present in unimain.py!"

test("unimain.py has no hardcoded /mnt/storage paths", test_no_hardcoded_paths)

def test_no_hardcoded_audio_worker():
    with open("audio_search_implementation_v2/worker.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert '/mnt/storage/organized_files/audio' not in content, \
        "Hardcoded audio path still in worker.py!"

test("audio worker.py has no hardcoded paths", test_no_hardcoded_audio_worker)


# ═══════════════════════════════════════════════════════════════
# STEP 3 — sqlite-vec availability
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 3: sqlite-vec")

def test_sqlite_vec_import():
    try:
        import sqlite_vec
        return True
    except ImportError:
        return "SKIP"

test("sqlite-vec is importable", test_sqlite_vec_import)


# ═══════════════════════════════════════════════════════════════
# STEP 4 — Video index module (structural checks)
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 4: Video index module structure")

def test_video_index_imports():
    import importlib
    spec = importlib.util.find_spec("video_search_implementation_v2.video_index")
    assert spec is not None, "Module not found on path"

test("video_index module is findable", test_video_index_imports)

def test_video_index_has_mmr():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "mmr_is_unique" in content, "MMR function not present"
    assert "selected_vecs" in content, "MMR selected_vecs logic not present"
    assert "0.985" not in content, "Old threshold 0.985 still present!"

test("video_index has MMR dedup logic", test_video_index_has_mmr)

def test_video_index_no_annoy():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "AnnoyIndex" not in content, "Annoy references still present!"
    assert ".npy" not in content, "npy file references still present!"
    assert "frame_vectors" in content, "sqlite-vec table not present"

test("video_index uses sqlite-vec (no Annoy)", test_video_index_no_annoy)

def test_video_index_has_transcript():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "transcribe" in content.lower(), "No transcript integration"
    assert "video_transcript" in content, "No video_transcript category"

test("video_index has transcript integration", test_video_index_has_transcript)

def test_video_index_has_descriptions():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "description" in content, "No description field"
    assert "_describe_frame" in content, "No describe_frame function"

test("video_index has frame descriptions", test_video_index_has_descriptions)

def test_video_index_atomic_cleanup():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "conn.rollback()" in content, "No rollback for atomic safety"
    assert "DELETE FROM frames WHERE video_id" in content, "No frame cleanup"

test("video_index has atomic cleanup", test_video_index_atomic_cleanup)

def test_video_search_configurable_topk():
    with open("video_search_implementation_v2/video_index.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "top_k: int = 5" in content, "top_k default should be 5"
    assert "hits[:2]" not in content, "Old hardcoded top-2 still present!"

test("video search has configurable top_k=5", test_video_search_configurable_topk)


# ═══════════════════════════════════════════════════════════════
# STEP 5 — Watchdog watcher
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 5: Filesystem watcher")

def test_watcher_exists():
    assert os.path.exists("video_search_implementation_v2/watcher.py")
    with open("video_search_implementation_v2/watcher.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "start_video_watcher" in content
    assert "stop_video_watcher" in content
    assert "watchdog" in content

test("watcher.py exists with start/stop API", test_watcher_exists)

def test_watchdog_import():
    try:
        import watchdog
        return True
    except ImportError:
        return "SKIP"

test("watchdog is importable", test_watchdog_import)


# ═══════════════════════════════════════════════════════════════
# STEP 6 — SDK Layer
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 6: SDK Layer (core/sdk.py)")

def test_sdk_structure():
    assert os.path.exists("core/__init__.py")
    assert os.path.exists("core/sdk.py")

test("core/ package exists", test_sdk_structure)

def test_sdk_class():
    with open("core/sdk.py", "r", encoding="utf-8") as f:
        content = f.read()
    required = [
        "class ContextCore",
        "def embed_text",
        "def embed_image",
        "def index_text",
        "def index_images",
        "def index_videos",
        "def index_audio",
        "def index_code",
        "def index_directory",
        "def search(",
        "def search_text",
        "def search_images",
        "def search_videos",
        "def start_watcher",
        "def stop_watcher",
    ]
    for r in required:
        assert r in content, f"Missing: {r}"

test("ContextCore has all required methods", test_sdk_class)


# ═══════════════════════════════════════════════════════════════
# STEP 7 — MCP Layer (fetch_content tool)
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 7: MCP Layer enhancements")

def test_mcp_fetch_content():
    with open("mcp_server.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "def fetch_content" in content, "fetch_content tool missing"
    assert "_fetch_video_content" in content, "video content fetcher missing"
    assert "_fetch_text_content" in content, "text content fetcher missing"

test("MCP has fetch_content tool", test_mcp_fetch_content)

def test_mcp_video_shaping():
    with open("mcp_server.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert '"description"' in content, "description field missing from video results"
    assert '"best_timestamp"' in content, "best_timestamp missing from video results"

test("MCP video results include description + timestamp", test_mcp_video_shaping)


# ═══════════════════════════════════════════════════════════════
# STEP 8 — requirements.txt
# ═══════════════════════════════════════════════════════════════
print("\n🔧 STEP 8: Requirements")

def test_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as f:
        content = f.read()
    assert "sqlite-vec" in content, "sqlite-vec missing from requirements"
    assert "watchdog" in content, "watchdog missing from requirements"

test("requirements.txt includes sqlite-vec and watchdog", test_requirements)


# ═══════════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*55}")
print(f"  RESULTS:  ✅ {passed} passed  |  ❌ {failed} failed  |  ⏭️  {skipped} skipped")
print(f"{'='*55}")

if failed > 0:
    print("\n⚠️  Some tests failed — review the output above.")
    sys.exit(1)
elif skipped > 0:
    print("\n📦 Some dependencies aren't installed yet.")
    print("   Run:  pip install sqlite-vec watchdog")
    print("   Then re-run this script.")
else:
    print("\n🎉 All tests passed! Implementation is structurally sound.")
