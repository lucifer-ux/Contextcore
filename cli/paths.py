# cli/paths.py
#
# Central SDK root resolution for the CLI.
# Works whether running from source or from a pip-installed venv.

import os
from pathlib import Path


def get_sdk_root() -> Path:
    """
    Find the actual SearchEmbedSDK root directory.

    Resolution order:
    1. CONTEXTCORE_SDK_ROOT env var (set explicitly)
    2. sdk_root key inside ~/.contextcore/contextcore.yaml
    3. Relative to this file (only works when running from source)
    """
    # 1. Env var override
    env = os.environ.get("CONTEXTCORE_SDK_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p

    # 2. Read from config YAML
    cfg = Path.home() / ".contextcore" / "contextcore.yaml"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("sdk_root:"):
                    val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    p = Path(val).expanduser().resolve()
                    if p.is_dir():
                        return p
        except Exception:
            pass

    # 3. Relative to this file (works in editable installs / source runs)
    relative = Path(__file__).resolve().parent.parent
    if (relative / "unimain.py").exists():
        return relative

    # 4. Final fallback — cwd
    return Path.cwd()


def get_mcp_script() -> Path:
    return get_sdk_root() / "mcp_server.py"


def get_default_config() -> Path:
    return Path.home() / ".contextcore" / "contextcore.yaml"
