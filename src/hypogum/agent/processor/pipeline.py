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

    # Bail early if no pending observations at all
    pending = await db.get_pending_observations(user_id, limit=1)
    if not pending:
        logger.info("No pending observations — skipping cycle")
        return None

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

    # Phase D: Tip generation — resume session if available, else standalone
    session_id = ingest_result.get("session_id")
    tips_before = {t["path"] for t in memory_store.list_tips(limit=50)}

    if session_id:
        await invoke_agent_continue(
            session_id=session_id,
            memory_dir=memory_store.root,
            prompt=render_prompt(config.prompts_dir, "tip_prompt.md"),
            serve_port=config.agent_serve_port,
            timeout=config.agent_timeout,
        )
    else:
        logger.info("No session_id from ingest, running tips standalone")
        await invoke_agent(
            task="tips",
            memory_dir=memory_store.root,
            prompt=render_prompt(config.prompts_dir, "tip_prompt.md"),
            serve_port=config.agent_serve_port,
            timeout=config.agent_timeout,
        )

    new_tips = [t for t in memory_store.list_tips(limit=10) if t["path"] not in tips_before]
    if new_tips:
        logger.info("Generated {} tip(s)", len(new_tips))

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
        logger.info("No tips generated")

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
