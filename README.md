# 🧠 ContextCore

> **The intelligent context layer between your AI and the world.**  
> Stop paying for noise. Let Claude see only what matters.

---

## The Problem

When Claude uses multiple MCP tools — Slack, Notion, Gmail, Jira — every tool dumps its **full raw output** into the context window. Claude sees thousands of tokens of noise to find a handful of relevant sentences.

**You pay for all of it.**

---

## The Solution

ContextCore sits between Claude and your data sources. It:

1. **Intercepts** all MCP tool calls
2. **Indexes** results using BM25 + SQLite FTS5 (text) and CLIP (images/video)
3. **Reranks** candidates by semantic similarity to the query
4. **Returns only the top 3–5 relevant chunks** to Claude

One SDK. One MCP tool for Claude to call. 20–30x fewer tokens.

```
Before ContextCore:   User → Claude → [Slack MCP + Notion MCP + Gmail MCP] → 8,000 tokens → Claude
After ContextCore:    User → Claude → [ContextCore] → 300 tokens → Claude
```

---

## Features

- 🔍 **Hybrid search** — BM25 keyword + semantic vector reranking
- 🖼️ **Multimodal** — text, images, video (via CLIP embeddings)
- 🪶 **Lightweight** — runs fully local on a laptop, zero infrastructure
- 🔌 **MCP native** — drop-in tool for Claude Desktop or any MCP host
- 🌐 **Language agnostic** — Python core, REST API for any language
- ☁️ **Cloud optional** — use local models or OpenAI/Anthropic embeddings
- 💾 **Single file storage** — everything in one portable SQLite database

---

## Quick Start

### Install

```bash
pip install contextcore
```

### Index your files

```python
from contextcore import ContextCore

cc = ContextCore()  # creates contextcore.db in current directory

# Index anything — text, images, video
cc.index("./docs")
cc.index("./slack_export.json", source="slack")
cc.index("./screenshots/", source="images")
```

### Query

```python
results = cc.search("budget discussion from last quarter", top_k=5)

for r in results:
    print(r.content)
    print(r.source, r.score)
```

That's it. Three lines to multimodal semantic search.

---

## Claude Desktop Integration (MCP)

ContextCore ships as a ready-to-use MCP server. Claude calls it as a single tool and never touches raw MCP output directly.

### 1. Start the MCP server

```bash
contextcore serve --db ./mydata.db --port 8080
```

### 2. Add to Claude Desktop config

```json
{
  "mcpServers": {
    "contextcore": {
      "command": "contextcore",
      "args": ["serve", "--db", "./mydata.db"],
      "env": {}
    }
  }
}
```

### 3. That's it

Claude now has one tool: `contextcore_search`. When it calls it, ContextCore internally fans out to your other MCPs, filters the results, and returns only what's relevant.

```
Claude → contextcore_search("Q3 budget issues")
       ↓
       ContextCore fans out to Slack, Notion, Gmail MCPs
       ↓
       Raw results: ~6,000 tokens
       ↓
       After filtering and reranking: ~280 tokens
       ↓
Claude receives clean, relevant context only
```

---

## REST API (Any Language)

If your codebase isn't Python, run ContextCore as a local service and call it over HTTP.

### Start the server

```bash
contextcore serve --db ./mydata.db --port 8080
```

### Call from JavaScript

```javascript
const response = await fetch("http://localhost:8080/search", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "deployment issues last week",
    top_k: 5
  })
});

const { results } = await response.json();
```

### Call from Go

```go
body := `{"query": "deployment issues last week", "top_k": 5}`
resp, _ := http.Post("http://localhost:8080/search", "application/json", strings.NewReader(body))
```

### Call from Ruby

```ruby
require 'net/http'
require 'json'

uri = URI('http://localhost:8080/search')
response = Net::HTTP.post(uri, { query: "deployment issues", top_k: 5 }.to_json, "Content-Type" => "application/json")
results = JSON.parse(response.body)
```

---

## Indexing Data Sources

### Local files

```python
cc.index("./documents/")           # recursively indexes all files
cc.index("./report.pdf")           # single file
cc.index("./images/")              # images via CLIP
cc.index("./recordings/")          # video keyframe extraction + CLIP
```

### Slack export

```python
cc.index("./slack_export.json", source="slack")
```

### From an MCP result (runtime indexing)

```python
# index MCP output on the fly so future queries skip the MCP call
cc.index_mcp_result(tool_name="notion", result=raw_notion_output, query_context="Q3 planning")
```

### Custom data

```python
cc.index_text(
    content="Your raw text here",
    metadata={"source": "internal-wiki", "date": "2025-11-01", "author": "alice"}
)
```

---

## Configuration

```python
from contextcore import ContextCore, Config

cc = ContextCore(config=Config(
    db_path="./contextcore.db",

    # Embedding model — local by default
    embedding_model="clip-vit-base-patch32",     # local, ~300MB
    # embedding_model="openai/text-embedding-3-small",  # cloud option

    # Search tuning
    bm25_candidates=100,    # how many FTS5 results to pull before reranking
    top_k_default=5,        # final results returned to caller

    # Chunking
    chunk_size=400,         # tokens per chunk
    chunk_overlap=50,

    # Cache
    mcp_cache_ttl_seconds=3600,  # 1 hour — serve from index, skip live MCP call
))
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   ContextCore                    │
│                                                  │
│  ┌──────────┐    ┌──────────┐    ┌────────────┐ │
│  │  Ingest  │───▶│  Chunk   │───▶│   Index    │ │
│  │  Layer   │    │  Engine  │    │  (SQLite)  │ │
│  └──────────┘    └──────────┘    └─────┬──────┘ │
│                                        │        │
│  ┌──────────┐    ┌──────────┐    ┌─────▼──────┐ │
│  │  Results │◀───│ Reranker │◀───│ BM25+CLIP  │ │
│  │   API    │    │(semantic)│    │   Search   │ │
│  └──────────┘    └──────────┘    └────────────┘ │
└─────────────────────────────────────────────────┘
         ▲                    ▲
    MCP Server           REST API
  (Claude Desktop)    (Any language)
```

**Storage**: Everything lives in a single `.db` file — FTS5 index, vector embeddings (sqlite-vec), chunk metadata, MCP cache, file registry.

**Query flow**:
1. FTS5 retrieves top 100 keyword candidates — milliseconds
2. CLIP/embedding model reranks to top 5 by semantic similarity
3. Parent chunks expanded for full context
4. Results returned with source, score, and metadata

---

## Supported File Types

| Type | Format | Engine |
|------|--------|--------|
| Text | `.txt`, `.md`, `.pdf`, `.docx` | BM25 + FTS5 |
| Code | `.py`, `.js`, `.ts`, `.go`, etc. | BM25 + FTS5 |
| Data | `.json`, `.csv` | BM25 + FTS5 |
| Images | `.jpg`, `.png`, `.webp` | CLIP |
| Video | `.mp4`, `.mov` (keyframes) | CLIP |
| Slack | export `.json` | BM25 + FTS5 |

---

## Cost Savings

A rough estimate for a team using Claude with 5 MCPs:

| | Without ContextCore | With ContextCore |
|---|---|---|
| Avg context per query | ~8,000 tokens | ~350 tokens |
| Queries per day | 500 | 500 |
| Monthly token cost | ~$400 | ~$18 |
| **Savings** | | **~95%** |

*Estimates based on Claude Sonnet pricing. Actual savings vary by use case.*

---

## Roadmap

- [ ] Automatic MCP discovery and proxying
- [ ] Web dashboard with live token savings counter
- [ ] Streaming results
- [ ] Multi-user / team support
- [ ] Managed cloud version (hosted indexing + sync)
- [ ] Connectors: Notion, Linear, GitHub Issues, Google Drive

---

## Contributing

Contributions welcome. Open an issue first for major changes.

```bash
git clone https://github.com/yourname/contextcore
cd contextcore
pip install -e ".[dev]"
pytest
```

---

## License

MIT — free to use, self-host, and build on.

---

<p align="center">
  Built for teams tired of paying Claude to read noise.
</p>
