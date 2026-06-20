# hypogum

Standalone background agent — observes your screen, analyzes activity via multimodal LLM, and generates proactive tips. Includes an MCP endpoint for external AI agents to query and add memory.

## Quick start

```bash
# Create venv and install
python -m venv .venv
.venv\Scripts\pip install -e ".[all]"       # Windows
.venv/bin/pip install -e ".[all]"            # macOS / Linux

# Set your LLM API key
cp .env.example .env
# Edit .env — fill in GOOGLE_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY)

# Run the background agent
hypogum agent
```

## Architecture

```
hypogum agent
├── observers/     ScreenObserver (mss), CameraObserver (cv2)
├── processor/     analyzer.py → tips.py → pipeline.py
├── db/            DBStore: LocalDBStore (aiosqlite) | RemoteDBStore (httpx)
├── vector/        VectorStore: LocalVectorStore (chromadb) | RemoteVectorStore
├── llm/           LLMProvider: Gemini | OpenAI | Anthropic
├── auth/          AuthProvider: NoAuth | JWT | OAuth2
└── utils/         Notifier (desktop notifications), WindowDetector
```

### Observer → Process → Tip flow

```
ScreenObserver ─┐
                ├─► observations/ (JPEG + JSON)
CameraObserver ─┘
                       │
                       ▼
              process_pending_observations()
                  ┌─ multimodal LLM analysis
                  ├─ embed items
                  ├─ deduplicate (cosine similarity)
                  └─ store in DB + vector DB
                       │
                       ▼
              generate_proactive_tip()
                  ┌─ search matching goals
                  ├─ search matching traits
                  └─ LLM generates actionable tips ⟶ desktop notification
```

## CLI

| Command | Purpose |
|---|---|
| `hypogum store` | Start remote data store HTTP server (FastAPI, `/api/v1/`) |
| `hypogum agent` | Run observer → process → tip background loop |
| `hypogum mcp --transport stdio` | MCP endpoint for Claude Desktop / VS Code |
| `hypogum mcp --transport http --port 8080` | MCP endpoint for remote AI agents |

## MCP tools

| Tool | Description |
|---|---|
| `query_memory(query, category?, limit=10)` | Semantic search across vector memory |
| `add_memory(content, category, evidence?, confidence=5, lifespan=5)` | Add entry to memory |
| `get_tips(limit=10, offset=0)` | Fetch recent proactive tips |
| `get_insights(limit=10, offset=0)` | Fetch recent analysis event summaries |
| `add_goal(content, evidence?)` | Add a goal to track |
| `capture_now()` | Trigger immediate screen capture |
| `list_categories()` | List all memory categories |

## Configuration

All settings via environment variables (see `.env.example`). Key ones:

| Variable | Default | Description |
|---|---|---|
| `HYPOGUM_LLM_PROVIDER` | `gemini` | `gemini`, `openai`, or `anthropic` |
| `GOOGLE_API_KEY` | — | API key for Gemini |
| `HYPOGUM_OBSERVE_SCREEN_INTERVAL` | `60` | Seconds between screen captures |
| `HYPOGUM_PROCESS_INTERVAL` | `300` | Seconds between analysis cycles |
| `HYPOGUM_DB_MODE` | `local` | `local` (SQLite) or `remote` (HTTP) |
| `HYPOGUM_VEC_MODE` | `local` | `local` (ChromaDB) or `remote` (HTTP) |

## Pluggable abstractions

| Layer | ABC | Local impl | Remote impl |
|---|---|---|---|
| Relational store | `DBStore` | `LocalDBStore` (aiosqlite) | `RemoteDBStore` (httpx) |
| Vector store | `VectorStore` | `LocalVectorStore` (chromadb) | `RemoteVectorStore` (httpx) |
| LLM provider | `LLMProvider` | `GeminiProvider` / `OpenAIProvider` / `AnthropicProvider` | — |
| Auth provider | `AuthProvider` | `NoAuthProvider` / `JWTAuthProvider` / `OAuth2Provider` | — |
| Observer | `Observer` | `ScreenObserver` (mss) / `CameraObserver` (cv2) | — |

## Data storage

- `data/app.db` — SQLite (observations, events, tips)
- `data/chroma.db/` — ChromaDB (vector embeddings)
- `data/observations/YYYY-MM-DD/artifacts/` — JPEG screenshots
- `data/observations/YYYY-MM-DD/entries/` — JSON observation metadata

## Install options

```bash
pip install -e ".[all]"        # Everything
pip install -e ".[agent,llm]"  # Just the agent + LLM
pip install -e ".[store]"      # Just the store server
pip install -e ".[mcp,llm]"    # Just the MCP endpoint
```
