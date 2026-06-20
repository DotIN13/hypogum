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
| `HYPOGUM_SCREEN_DEDUP_ENABLED` | `true` | Discard a screenshot too similar to the previous saved one |
| `HYPOGUM_SCREEN_DEDUP_THRESHOLD` | `10` | Max dHash Hamming distance treated as a duplicate (0..hash_size²) |
| `HYPOGUM_SCREEN_DEDUP_HASH_SIZE` | `16` | dHash grid size; higher = more sensitive to small on-screen changes |
| `HYPOGUM_PROCESS_INTERVAL` | `300` | Seconds between analysis cycles |
| `HYPOGUM_PAUSE_WHEN_LOCKED` | `true` | Pause observing + processing while the workstation is locked |
| `HYPOGUM_PAUSE_WHEN_IDLE` | `false` | Pause once there's no user input for `HYPOGUM_IDLE_THRESHOLD` seconds |
| `HYPOGUM_IDLE_THRESHOLD` | `300` | Idle seconds before pausing |
| `HYPOGUM_DB_MODE` | `local` | `local` (SQLite) or `remote` (HTTP) |
| `HYPOGUM_VEC_MODE` | `local` | `local` (ChromaDB) or `remote` (HTTP) |

### Idle / lock pausing

When the system is locked or has been idle past `HYPOGUM_IDLE_THRESHOLD`, the agent
skips screen/camera capture *and* the LLM analysis/tip cycle (timers keep running, so
it resumes automatically once you're active). Detection is dependency-free:

| OS | Idle | Lock |
|---|---|---|
| Windows | `GetLastInputInfo` (ctypes) | `OpenInputDesktop` (ctypes) |
| macOS | `ioreg` `HIDIdleTime` | `Quartz` if `pyobjc` is installed, else covered by idle |
| Linux | `xprintidle` (X11; n/a on Wayland) | `gdbus` GNOME/freedesktop `ScreenSaver`, else covered by idle |

Where idle can't be measured (e.g. Wayland), only lock pausing applies.

### Screen deduplication

Each screenshot is fingerprinted with a dHash (`HYPOGUM_SCREEN_DEDUP_HASH_SIZE`×N
grid) and compared to the previously saved one; if the Hamming distance is
`<= HYPOGUM_SCREEN_DEDUP_THRESHOLD` the frame is discarded before any encode/disk/DB
work, so static screens don't pile up redundant captures. A larger hash size detects
smaller on-screen changes. Set `HYPOGUM_SCREEN_DEDUP_ENABLED=false` to keep every frame.

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
