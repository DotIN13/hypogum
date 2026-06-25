import asyncio
import json
from pathlib import Path

from loguru import logger

from hypogum.agent.prompts import render_prompt
from hypogum.agent.scheduler import IntervalTask
from hypogum.agent.utils.notifier import Notifier
from hypogum.config import Config
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider
from hypogum.memory.agent import invoke_agent, invoke_agent_continue
from hypogum.memory.store import MemoryStore


TIP_PROMPT = """Based on everything you know about the user — recent activity on screen, stored goals, traits, and events in memory — generate actionable proactive tips.

1. Read recent memory pages (goals, traits, events, log.md) to understand current context.
2. Identify 1-3 high-impact, immediately actionable tips.
3. For each tip, write a markdown file to memory/tips/<goal-slug>/<timestamp>-<slug>.md

Each tip file must follow this format exactly:

---
type: tip
goal: <goal-slug>
created: <ISO-8601 timestamp>
summary: <one-sentence summary of the suggestion>
---

# Tip: <short title>

**Suggestion:** one-sentence actionable step.

**Rationale:** why this matters right now, citing specific evidence from memory.
```

File naming: `memory/tips/<goal-slug>/<YYYY-MM-DDTHHMMSS>Z-<short-slug>.md`

Goal directory slugs should match existing goal page filenames (e.g., `refactor-zmtiles-pipeline`).
If no matching goal directory exists, create it.
Focus on tips the user can act on immediately."""


async def run_processing_cycle(
    user_id: str,
    db: DBStore,
    llm: LLMProvider,
    memory_store: MemoryStore,
    observers: list,
    *,
    prompts_dir: Path,
    data_dir: Path,
    config: Config,
    notifier: Notifier | None = None,
) -> dict | None:
    """One processing cycle: describe → save event → ingest + tips in same session."""

    # Phase A: Run all observers' describe steps
    products: list[str] = []
    for obs in observers:
        product_path = await obs.describe(
            db, user_id, data_dir, llm=llm, prompts_dir=prompts_dir,
        )
        if product_path:
            products.append(product_path)

    if not products:
        logger.info("No products generated — skipping process cycle")
        return None

    logger.info("Generated {} product(s): {}", len(products), products)

    # Phase B: Derive summary from first screen product, save event
    summary = ""
    for p in products:
        if "screen" in p:
            prod_abs = data_dir / p
            if prod_abs.exists():
                text = prod_abs.read_text(encoding="utf-8")
                summary = text[:500]
            break
    if not summary:
        summary = ", ".join(products)

    import time
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    event_id = await db.save_event(
        user_id,
        timestamp,
        summary[:500],
        ", ".join(products),
        json.dumps({"products": products}),
    )

    # Phase C: Invoke ingest agent
    tasks_dir = memory_store.root / ".tasks" / "ingest-input"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    (tasks_dir / "products.txt").write_text(
        "\n".join(products), encoding="utf-8",
    )

    (tasks_dir / "context.json").write_text(
        json.dumps({"timestamp": timestamp, "event_id": event_id}), encoding="utf-8",
    )

    ingest_prompt = render_prompt(
        config.prompts_dir, "ingest_prompt.md",
        memory_path="memory",
    )
    ingest_result = await invoke_agent(
        task="ingest",
        memory_dir=memory_store.root,
        prompt=ingest_prompt,
        serve_port=config.agent_serve_port,
        timeout=config.agent_timeout,
    )
    if ingest_result.get("status") == "ok":
        logger.info("Memory ingest completed: {}", ingest_result)
    else:
        logger.warning("Memory ingest issue: {}", ingest_result)

    # Phase D: Follow-up tip generation in the same opencode session
    session_id = ingest_result.get("session_id")
    if session_id:
        tip_result = await invoke_agent_continue(
            session_id=session_id,
            memory_dir=memory_store.root,
            prompt=TIP_PROMPT,
            serve_port=config.agent_serve_port,
            timeout=config.agent_timeout,
        )
        if tip_result.get("status") == "ok":
            new_tips = memory_store.list_tips(limit=3)
            if new_tips:
                logger.info("Generated {} tip(s) in session {}", len(new_tips), session_id)

                if config.notify_on_tips and notifier:
                    first = new_tips[0]
                    goal = first.get("goal", "you")[:50]
                    summary = first.get("summary", "")[:120]
                    title = f"Tip for: {goal}"
                    body = summary
                    if len(new_tips) > 1:
                        body += f" (+{len(new_tips) - 1} more)"
                    await notifier.notify(title, body)
            else:
                logger.info("No tips generated in session {}", session_id)
        else:
            logger.warning("Tip follow-up issue: {}", tip_result)
    else:
        logger.warning("No session_id from ingest, skipping inline tips")

    result = {"event_id": event_id, "summary": summary[:200], "products": products}
    return result


async def run_processing_loop(
    db: DBStore,
    llm: LLMProvider,
    user_id: str,
    config: Config,
    stop_event: asyncio.Event,
    memory_store: MemoryStore,
    observers: list,
    notifier: Notifier | None = None,
    pause_gate=None,
) -> None:
    """Run processing cycles on interval until stop_event is set.

    Uses a ticker that marks the task PENDING every interval and a
    worker that picks it up, runs the cycle, and returns to monitoring.
    Processing and tips share the same opencode session — tips are
    generated as a follow-up after ingest completes.
    """
    task = IntervalTask(
        "process",
        config.process_interval,
        pause_gate=pause_gate,
        stop_event=stop_event,
    )

    async def do_work():
        result = await run_processing_cycle(
            user_id, db, llm, memory_store, observers,
            prompts_dir=config.prompts_dir,
            data_dir=config.data_dir,
            config=config,
            notifier=notifier,
        )
        if result:
            logger.info("Saved event: {}", result.get("summary", "")[:100])
        else:
            logger.info("No new products — skipping process cycle")

    await task.run(do_work)
