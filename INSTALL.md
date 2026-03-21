# ContextCore — Getting Started

## Step 1: Install (< 2 minutes, no model downloads)

Open PowerShell and run:

```powershell
# Option A: Use the bootstrap script (recommended)
powershell -ExecutionPolicy Bypass -File install.ps1

# Option B: Manual steps
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```


This installs only the **lightweight base** — FastAPI, the MCP server, and the CLI.
Heavy ML models (torch, whisper) are downloaded later on-demand.

---

## Step 2: First-time setup wizard

```powershell
contextcore init
```

The wizard guides you through:
1. **Pick a folder to watch** (e.g. `~/Documents`)
2. **Choose what to search** — Text, Images, Audio, Video
3. **Storage location** for your index
4. **Auto-register** with Claude Desktop / Cline / Cursor
5. **Background indexing** kicks off automatically

Total time: under 2 minutes (excluding model downloads if you selected Images/Audio).

---

## Step 3: Use it

After setup, try asking Claude Desktop:
> "Search my documents for anything about project budgets"

---

## Daily commands

```
contextcore status        — Is it running? What's indexed?
contextcore index         — Scan for new files now
contextcore index <path>  — Index a specific folder
contextcore doctor        — Diagnose problems
contextcore serve         — Start the server manually
```

## Install optional ML models

```
contextcore install clip     — Image + video search (~300MB)
contextcore install audio    — Audio + meeting transcription (~150MB)
contextcore install all      — Everything
```

## Troubleshooting

Run `contextcore doctor` — it checks every component and gives a specific Fix: command for each problem.

---

## Requirements

- Python 3.10 or later
- Windows, macOS, or Linux
- ~200MB disk space (base install)
- Claude Desktop, Claude Code, Cline, or Cursor (for MCP integration)
