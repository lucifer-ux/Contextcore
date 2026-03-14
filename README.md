# ContextCore

ContextCore is a local CLI + backend + MCP integration layer for searching text, images, audio, and video from AI tools such as Claude Desktop.

This README is intentionally focused on:
- how to install it
- how to run it
- how to connect it to Claude
- how to verify that indexing and search are working
- how to troubleshoot common failures

It does not try to explain the internal code architecture.

## What ContextCore Does

ContextCore gives you:
- a CLI command: `contextcore`
- a local backend server, normally on `http://127.0.0.1:8000`
- an MCP server script for Claude and similar tools
- local indexing for:
  - text and documents
  - images
  - audio transcripts
  - video embeddings and video context

## Recommended Setup

For real usage, the most reliable setup is:
- keep one dedicated Python virtual environment
- use that same Python environment for:
  - `contextcore init`
  - `contextcore serve`
  - `mcp_server.py` in your Claude config

Do not test the backend in one venv and point Claude at a different venv. That is one of the most common causes of "it works in the terminal but not in Claude".

## Prerequisites

You need:
- Python 3.10+
- Windows, macOS, or Linux
- internet access for first-time model downloads
- enough disk space for Python packages and model files

Optional but important:
- `ffmpeg` for video indexing
- Claude Desktop or another MCP-capable tool if you want interactive AI integration

## Quick Install

### Windows (PowerShell)

Quick start (pipe to PowerShell - review first):
```powershell
irm https://your-domain.com/install.ps1 | iex
```

Safe start (download and inspect first):
```powershell
Invoke-WebRequest -Uri https://your-domain.com/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1
```

### macOS / Linux (bash)

Quick start (pipe to bash - review first):
```bash
curl -sL https://your-domain.com/install.sh | bash
```

Safe start (download and inspect first):
```bash
curl -sL https://your-domain.com/install.sh -o install.sh
chmod +x install.sh && ./install.sh
```

After installation, open a NEW terminal and run:
```bash
contextcore init
```

## Install From Source

### Windows

```powershell
cd C:\path\to\SearchEmbedSDK

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### macOS / Linux

```bash
cd /path/to/SearchEmbedSDK

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Verify Install

Run:

```powershell
contextcore --help
```

If that fails, the venv is either not activated or the editable install did not complete.

## First-Time Setup

Run:

```powershell
contextcore init
```

The setup wizard walks through:
- directory to watch
- modalities to enable
- storage location
- optional MCP registration
- backend startup
- initial indexing

### Recommended choices

If you want full multimodal support, enable:
- `text`
- `image`
- `audio`
- `video`

If you only want to test quickly, point it to a small folder with a few known files.

## What `contextcore init` Does

Depending on what you select, `contextcore init` may:
- write `~/.contextcore/contextcore.yaml`
- install heavy Python dependencies
- install or detect `ffmpeg`
- prewarm CLIP and Whisper models
- start the backend server
- start the initial indexing scan
- optionally update MCP tool configs

## Daily Commands

### Show status

```powershell
contextcore status
```

This shows:
- whether the backend server is running
- whether the MCP server script is present
- counts for text, images, audio, and video
- whether video runtime dependencies are available

### Run indexing again

```powershell
contextcore index
```

Or for a specific folder:

```powershell
contextcore index "C:\Users\USER\Documents\test"
```

### Start backend manually

```powershell
contextcore serve
```

By default, ContextCore uses port `8000`.

### Diagnose setup problems

```powershell
contextcore doctor
```

### Register with a tool later

```powershell
contextcore register claude-desktop
contextcore register claude-code
contextcore register cursor
contextcore register cline
```

### Install optional model stacks manually

```powershell
contextcore install clip
contextcore install audio
contextcore install all
```

## Expected Status Output

A healthy setup usually looks like:

```text
Server
------------------------------------------------------------------------------
  [OK] Running on port 8000
  [OK] MCP server script found

Index Progress
------------------------------------------------------------------------------
  Text     > 0   ready
  Images   > 0   ready
  Audio    > 0   ready
  Video    > 0   ready
```

If `Video` shows `missing ffmpeg`, video indexing is not ready.

If `Video` shows `model unavailable`, the CLIP model is not ready in the active environment.

## Claude Desktop Setup

Use the same Python executable that you used for the CLI and backend.

Example Claude MCP config:

```json
{
  "mcpServers": {
    "contextcore": {
      "command": "C:\\Users\\USER\\Documents\\SDKSearchImplementation\\SearchEmbedSDK\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\USER\\Documents\\SDKSearchImplementation\\SearchEmbedSDK\\mcp_server.py"
      ],
      "cwd": "C:\\Users\\USER\\Documents\\SDKSearchImplementation\\SearchEmbedSDK",
      "env": {
        "CONTEXTCORE_API_BASE_URL": "http://127.0.0.1:8000",
        "CONTEXTCORE_MCP_TIMEOUT_SECONDS": "120"
      }
    }
  }
}
```

Important:
- `command` should point to the Python inside the venv you are actively using
- `args` should point to this repo's `mcp_server.py`
- `cwd` should be the repo root
- `CONTEXTCORE_API_BASE_URL` should match the backend server port

After changing Claude config:
- fully quit Claude Desktop
- start the backend if it is not already running
- reopen Claude Desktop

## Backend Health Check

You can verify the backend directly:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

If the backend is healthy, you should get a successful response.

## Reset and Re-Test From Scratch

If you want to test like a fresh user, remove the venv and recreate it.

### Windows

```powershell
deactivate 2>$null

Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -like 'C:\path\to\SearchEmbedSDK\.venv*'
} | Select-Object ProcessId, ExecutablePath, CommandLine

Stop-Process -Id <PID> -Force

Remove-Item -Recurse -Force C:\path\to\SearchEmbedSDK\.venv
```

Then reinstall:

```powershell
cd C:\path\to\SearchEmbedSDK
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

Then rerun:

```powershell
contextcore init
```

## Troubleshooting

### 1. `contextcore` command not found

Cause:
- venv not activated
- editable install not run

Fix:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. `contextcore init` fails on import errors

Cause:
- dependencies were not installed into the active venv
- wrong Python interpreter is being used

Fix:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

Then verify:

```powershell
python -c "import questionary, typer, fastapi; print('ok')"
```

### 3. Server is healthy, but Claude says ContextCore is unavailable

Cause:
- Claude is using a different Python environment than the backend
- Claude config points at the wrong `python.exe`
- `cwd` is missing or wrong

Fix:
- use the same venv in both places
- update Claude config `command`
- add `cwd`
- restart Claude Desktop fully

### 4. Video says `missing ffmpeg`

Cause:
- `ffmpeg` is not installed
- `ffmpeg` exists but is not resolvable in the active runtime

Check:

```powershell
where.exe ffmpeg
ffmpeg -version
```

If not found:
- Windows: install via `winget`
- macOS: install via `brew`
- Linux: install via package manager

Examples:

```powershell
winget install Gyan.FFmpeg
```

```bash
brew install ffmpeg
sudo apt install ffmpeg
```

Then rerun:

```powershell
contextcore init
```

or:

```powershell
contextcore install all
```

### 5. Video says `model unavailable`

Cause:
- CLIP dependencies are installed but model files are not ready
- the wrong venv is being used

Fix:

```powershell
contextcore install clip
```

Then recheck:

```powershell
contextcore status
```

### 6. Audio is not indexing

Cause:
- Whisper is missing
- wrong venv
- unsupported or unreadable audio file

Fix:

```powershell
contextcore install audio
contextcore index
```

### 7. Backend starts, but indexing results stay at zero

Check:
- does the watched folder actually contain supported files?
- does `contextcore.yaml` point to the folder you think it does?

Your config usually lives at:

```text
C:\Users\USER\.contextcore\contextcore.yaml
```

Verify:
- `organized_root`
- `audio_directories`
- `video_directories`

Then run:

```powershell
contextcore index
contextcore status
```

### 8. Port mismatch between backend and Claude

ContextCore should use port `8000` unless you override it.

Check backend:

```powershell
contextcore status
```

Check Claude config:

```json
"CONTEXTCORE_API_BASE_URL": "http://127.0.0.1:8000"
```

These must match.

### 9. Old background servers are still running

Find them:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'uvicorn unimain:app|mcp_server.py'
} | Select-Object ProcessId, ExecutablePath, CommandLine
```

Stop them:

```powershell
Stop-Process -Id <PID> -Force
```

Then start cleanly:

```powershell
contextcore serve
```

### 10. Git or IDE shows huge numbers of changes

Cause:
- virtual environments inside the workspace
- caches
- logs
- local config files

Do not create test venvs inside broad workspace roots unless they are ignored.

The repo already ignores common noise such as:
- `.venv/`
- `.venv-test/`
- storage DBs
- `__pycache__`
- logs

If your IDE still shows thousands of changes:
- refresh Source Control
- reload the IDE window
- verify your IDE workspace is rooted at the repo you actually want

## Recommended End-to-End Test

1. Create or activate the repo-local `.venv`
2. Install:

```powershell
pip install -r requirements.txt
pip install -e .
```

3. Run:

```powershell
contextcore init
```

4. Point it at a folder with known sample files
5. Enable all modalities
6. Check:

```powershell
contextcore status
```

7. Confirm backend:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

8. Confirm Claude config uses the same venv
9. Restart Claude Desktop
10. Test search from Claude

## Files You Will Commonly Use

- repo config loader:
  - `config.py`
- backend entry:
  - `unimain.py`
- MCP bridge:
  - `mcp_server.py`
- user config:
  - `~/.contextcore/contextcore.yaml`

## If You Need Help

When diagnosing problems, the highest-signal commands are:

```powershell
contextcore status
contextcore doctor
where.exe ffmpeg
Invoke-WebRequest http://127.0.0.1:8000/health
```

If something still fails, capture:
- the exact command you ran
- the full traceback or terminal output
- your `contextcore status` output
- the Python path used by Claude in your MCP config

That is usually enough to isolate the issue quickly.
