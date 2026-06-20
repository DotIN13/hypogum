import json
import datetime
import uuid
import time

from loguru import logger

from hypogum.config import Config
from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore
from hypogum.llm.base import LLMProvider
from hypogum.agent.processor.analyzer import _merge_evidence
from hypogum.agent.observers.screen import ScreenObserver


def create_mcp_server(
    config: Config,
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    user_id: str,
):
    """Build a FastMCP server with hypogum memory tools."""

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("hypogum")

    @mcp.tool()
    async def query_memory(query: str, category: str | None = None, limit: int = 10) -> list[dict]:
        """Semantic search across vector memory: personalities, skills, interests, events, goals, etc."""
        embeddings = await llm.embed([query])
        results = await vec.search(
            user_id, embeddings[0], limit=limit, item_type=category,
        )
        return results

    @mcp.tool()
    async def add_memory(
        content: str,
        category: str,
        evidence: str | None = None,
        confidence: int = 5,
        lifespan: int = 5,
    ) -> dict:
        """Add an entry to vector memory."""
        valid_categories = [
            "goal", "event", "personality", "skill", "interest",
            "preference", "ownership", "relationship", "weakness",
        ]
        if category not in valid_categories:
            raise ValueError(f"Invalid category '{category}'. Must be: {', '.join(valid_categories)}")

        confidence = max(1, min(10, int(confidence)))
        lifespan = max(1, min(10, int(lifespan)))
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        content_text = f"{category}: {content}"
        embeddings = await llm.embed([content_text])
        embedding = embeddings[0]

        new_evidence = json.dumps(
            [{"text": evidence or "manually added via MCP", "timestamp": ts}],
            ensure_ascii=False,
        )

        if category == "event":
            existing = None
        else:
            existing, _, _ = await vec.find_similar(
                user_id, embedding, category, config.merge_threshold,
            )

        if existing:
            merged_evidence = _merge_evidence(
                existing.get("evidence", ""), new_evidence,
            )
            merged_meta = {
                "type": category,
                "content": content_text,
                "timestamp": existing.get("timestamp", ts),
                "user_id": user_id,
                "user_event_id": existing.get("user_event_id", "0"),
                "confidence": max(confidence, int(existing.get("confidence", 0))),
                "evidence": merged_evidence,
                "lifespan": max(lifespan, int(existing.get("lifespan", 0))),
            }
            await vec.update_metadata(user_id, existing["id"], merged_meta)
            logger.info("Memory merged [{}]: {}", category, content[:80])
            return {"status": "ok", "merged": True, "id": existing["id"]}
        else:
            mem_id = f"mcp_{uuid.uuid4().hex[:12]}"
            await vec.add(user_id, [{
                "id": mem_id,
                "vector": embedding,
                "metadata": {
                    "type": category,
                    "content": content_text,
                    "timestamp": ts,
                    "user_id": user_id,
                    "user_event_id": "0",
                    "confidence": confidence,
                    "evidence": new_evidence,
                    "lifespan": lifespan,
                },
            }])
            logger.info("Memory added [{}]: {}", category, content[:80])
            return {"status": "ok", "merged": False, "id": mem_id}

    @mcp.tool()
    async def get_tips(limit: int = 10, offset: int = 0) -> list[dict]:
        """Fetch recent proactive tips."""
        items, _ = await db.get_tips(user_id, limit, offset)
        return items

    @mcp.tool()
    async def get_insights(limit: int = 10, offset: int = 0) -> list[dict]:
        """Fetch recent analysis event summaries."""
        items, _ = await db.get_events(user_id, limit, offset)
        return items

    @mcp.tool()
    async def add_goal(content: str, evidence: str | None = None) -> dict:
        """Add a goal to track."""
        return await add_memory(content=content, category="goal", evidence=evidence, confidence=5, lifespan=8)

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
                "preference", "ownership", "relationship", "weakness"]

    return mcp
