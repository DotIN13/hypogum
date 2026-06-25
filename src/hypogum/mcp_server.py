from loguru import logger

from hypogum.agent.observers.screen import ScreenObserver
from hypogum.config import Config
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider
from hypogum.memory.search import search_memory
from hypogum.memory.store import MemoryStore


def create_mcp_server(
    config: Config,
    db: DBStore,
    llm: LLMProvider,
    memory_store: MemoryStore,
    user_id: str,
):
    """Build a FastMCP server with hypogum memory tools."""

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("hypogum")

    @mcp.tool()
    async def memory_search(query: str, limit: int = 10) -> list[dict]:
        """Search memory pages with ripgrep. Returns matching snippets with file and line info."""
        return search_memory(query, memory_store.root, max_results=limit)

    @mcp.tool()
    async def memory_add(
        content: str,
        category: str,
        evidence: str | None = None,
        confidence: int = 5,
        lifespan: int = 5,
    ) -> dict:
        """Create or update a memory page."""
        from hypogum.config import now_local, tz_label

        valid_categories = [
            "goal", "event", "personality", "skill", "interest",
            "preference", "ownership", "relationship", "weakness", "struggle",
        ]
        if category not in valid_categories:
            raise ValueError(f"Invalid category '{category}'. Must be: {', '.join(valid_categories)}")

        confidence = max(1, min(10, int(confidence)))
        lifespan = max(1, min(10, int(lifespan)))

        local_now = now_local(config.timezone)
        timestamp = local_now.isoformat(timespec="seconds")
        date_str = local_now.strftime("%Y-%m-%d")
        tz = tz_label(config.timezone)

        if category == "event":
            ev = evidence or "manually added via MCP"
            slug = content.lower().replace(" ", "_").replace("/", "_")[:60]
            safe_hm = local_now.strftime("%H%M")
            path = f"calendar_events/observed/{date_str}T{safe_hm}_event_{slug}.md"
            body = f"""---
type: calendar_event
source: user
significant: true
date: {date_str}
start: {timestamp}
end:
tz: {tz}
category: event
title: {content}
confidence: {confidence}
lifespan: {lifespan}
last_updated: {timestamp}
evidence_count: 1
tags: []
related: []
---

# {content}

{content}

## Evidence
- [{date_str}] {ev}

## History
- {date_str}: created via MCP
"""
            memory_store.write_page(path, body)
            logger.info(
                "Significant calendar event added via MCP: {} [{}]", content[:80], path,
            )
            return {"status": "ok", "path": path, "created": True}

        if category in ("weakness", "struggle"):
            ev = evidence or "manually added via MCP"
            slug = content.lower().replace(" ", "_").replace("/", "_")[:60]
            subdir = "weaknesses" if category == "weakness" else "struggles"
            path = f"{subdir}/{slug}.md"
            body = f"""---
type: {category}
confidence: {confidence}
lifespan: {lifespan}
last_updated: {timestamp}
evidence_count: 1
tags: []
related: []
---

# {content}

{content}

## Evidence
- [{date_str}] {ev}

## History
- {date_str}: created via MCP
"""
            memory_store.write_page(path, body)
            logger.info("Memory {}: {} [{}]", "added", content[:80], path)
            return {"status": "ok", "path": path, "created": True}

        subtype_map = {
            "personality": "personality", "skill": "skill", "interest": "interest",
            "preference": "preference", "ownership": "ownership",
            "relationship": "relationship",
        }
        subtype = subtype_map.get(category)

        category_dir = {
            "goal": "goals",
        }
        subdir = category_dir.get(category, "traits")

        slug = content.lower().replace(" ", "_").replace("/", "_")[:60]
        path = f"{subdir}/{slug}.md"

        existing_content = ""
        try:
            existing_content = memory_store.read_page(path)
        except FileNotFoundError:
            pass

        ev = evidence or "manually added via MCP"
        evidence_entry = f"- [{date_str}] {ev}"

        if existing_content:
            new_body = existing_content + "\n" + evidence_entry + "\n"
        else:
            new_body = f"""---
type: {"goal" if category == "goal" else "trait"}
{'subtype: ' + subtype if subtype else ''}
confidence: {confidence}
lifespan: {lifespan}
last_updated: {timestamp}
evidence_count: 1
tags: []
related: []
---

# {content}

{content}

## Evidence
{evidence_entry}

## History
- {date_str}: created via MCP
"""

        memory_store.write_page(path, new_body)
        logger.info("Memory {}: {} [{}]", "updated" if existing_content else "added", content[:80], path)
        return {"status": "ok", "path": path, "created": not existing_content}

    @mcp.tool()
    async def memory_read(path: str) -> dict:
        """Read a memory page by path (e.g. 'traits/Python.md')."""
        try:
            content = memory_store.read_page(path)
            return {"path": path, "content": content}
        except FileNotFoundError:
            return {"error": f"Page not found: {path}"}

    @mcp.tool()
    async def memory_list(subdir: str | None = None) -> list[str]:
        """List memory pages, optionally filtered by subdirectory (entities, traits, goals, tips, weaknesses, struggles, calendar_events/observed, ...)."""
        return memory_store.list_pages(subdir)

    @mcp.tool()
    async def memory_index() -> str:
        """Read index.md — the catalog of all memory pages."""
        return memory_store.get_index()

    @mcp.tool()
    async def memory_log(limit: int = 50) -> str:
        """Read log.md — the chronological audit trail."""
        return memory_store.get_log(limit=limit)

    @mcp.tool()
    async def get_tips(limit: int = 10) -> list[dict]:
        """Fetch recent proactive tips from the file-based tip store."""
        return memory_store.list_tips(limit=limit)

    @mcp.tool()
    async def get_insights(limit: int = 10, offset: int = 0) -> list[dict]:
        """Fetch recent activity from the calendar (observed/ bucket, newest first)."""
        from hypogum.calendar.parse import recent_observed_entries
        return recent_observed_entries(memory_store.root, limit, offset)

    @mcp.tool()
    async def calendar_add(note: str) -> dict:
        """Queue a calendar note for the agent to ingest into calendar_events/.

        Free text — e.g. 'standup every weekday 9am' or 'lunch with Alice Tue 12-1pm',
        or 'spent the afternoon refactoring'. The ingest agent parses it into a
        source:user planned/actual (or recurring) calendar event.
        """
        import uuid

        from hypogum.config import now_local

        inbox = memory_store.root / ".tasks" / "user-input"
        inbox.mkdir(parents=True, exist_ok=True)
        ts = now_local(config.timezone).strftime("%Y-%m-%dT%H-%M-%S")
        path = inbox / f"mcp_{ts}_{uuid.uuid4().hex[:6]}.md"
        path.write_text(note.strip() + "\n", encoding="utf-8")
        logger.info("Queued calendar note via MCP: {}", path.name)
        return {"status": "ok", "queued": path.name}

    @mcp.tool()
    async def add_goal(content: str, evidence: str | None = None) -> dict:
        """Add a goal to track."""
        return await memory_add(content=content, category="goal", evidence=evidence, confidence=5, lifespan=8)

    @mcp.tool()
    async def capture_now() -> dict:
        """Trigger immediate screen capture."""
        screen = ScreenObserver()
        obs_id = await screen.observe(
            db, user_id, config.data_dir,
            max_width=config.observe_max_width, quality=config.observe_quality,
        )
        if obs_id is not None:
            return {"status": "ok", "observation_id": obs_id}
        return {"status": "error", "message": "Screen capture failed"}

    @mcp.tool()
    async def list_categories() -> list[str]:
        """List all memory categories."""
        return ["goal", "event", "personality", "skill", "interest",
                "preference", "ownership", "relationship", "weakness", "struggle"]

    return mcp
