
import sys
from pathlib import Path

# Add root to path
root = Path(r"c:\Users\USER\Documents\SDKSearchImplementation\SearchEmbedSDK")
sys.path.insert(0, str(root))

from video_search_implementation_v2.video_index import extract_frames_scene_or_sample, _cleanup_tmpdir

video_path = r"C:\Users\USER\Documents\test\mcp_tool_demo.mp4"

print(f"Testing frame extraction for: {video_path}")
try:
    tmpdir, frames = extract_frames_scene_or_sample(video_path, max_frames=5)
    print(f"Extraction successful!")
    print(f"Tmpdir: {tmpdir}")
    print(f"Frames found: {len(frames)}")
    for f, ts in frames:
        print(f"  - {f} at {ts}s")
    _cleanup_tmpdir(tmpdir)
except Exception as e:
    print(f"Extraction failed with error: {e}")
    import traceback
    traceback.print_exc()
