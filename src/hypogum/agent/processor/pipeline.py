import asyncio
import datetime
import json
from pathlib import Path

from loguru import logger

from hypogum.agent.prompts import render_prompt
from hypogum.agent.scheduler import IntervalTask
from hypogum.agent.utils.notifier import Notifier
from hypogum.config import Config, resolve_timezone
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
    """One processing cycle: describe → ingest (calendar) + tips in one session."""

    # Bail early if no pending observations at all
    pending = await db.get_pending_observations(user_id, limit=1)
    if not pending:
        logger.info("No pending observations — skipping cycle")
        return None

    # Resolve local time + tz once for this cycle (used by describe and the agent).
    tz = resolve_timezone(config.timezone)
    local_now = datetime.datetime.now(tz)
    local_date = local_now.strftime("%Y-%m-%d")
    tz_name = getattr(tz, "key", None) or local_now.strftime("%Z") or str(tz)

    # Phase A: Run all observers' describe steps
    products: list[str] = []
    for obs in observers:
        product_path = await obs.describe(
            db, user_id, data_dir, llm=llm, prompts_dir=prompts_dir,
            tz_name=config.timezone,
        )
        if product_path:
            products.append(product_path)

    if not products:
        logger.info("No products generated — skipping process cycle")
        return None

    logger.info("Generated {} product(s): {}", len(products), products)

    # Phase B: Derive a short summary (for logging) from the screen product body.
    summary = ""
    for p in products:
        if "screen" in p:
            prod_abs = data_dir / p
            if prod_abs.exists():
                from hypogum.calendar.parse import body_after_frontmatter
                text = prod_abs.read_text(encoding="utf-8")
                summary = body_after_frontmatter(text)[:500]
            break
    if not summary:
        summary = ", ".join(products)

    # Phase C: Invoke ingest agent
    tasks_dir = memory_store.root / ".tasks" / "ingest-input"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    (tasks_dir / "products.txt").write_text(
        "\n".join(products), encoding="utf-8",
    )

    (tasks_dir / "context.json").write_text(
        json.dumps({
            "local_now": local_now.isoformat(timespec="seconds"),
            "local_date": local_date,
            "tz": tz_name,
        }),
        encoding="utf-8",
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
        model=config.agent_model,
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
            model=config.agent_model,
        )
    else:
        logger.info("No session_id from ingest, running tips standalone")
        await invoke_agent(
            task="tips",
            memory_dir=memory_store.root,
            prompt=render_prompt(config.prompts_dir, "tip_prompt.md"),
            serve_port=config.agent_serve_port,
            timeout=config.agent_timeout,
            model=config.agent_model,
        )

    new_tips = [t for t in memory_store.list_tips(limit=10) if t["path"] not in tips_before]
    if new_tips:
        logger.info("Generated {} tip(s)", len(new_tips))

        if config.notify_on_tips and notifier:
            first = new_tips[0]
            category = first.get("category", "general")[:50]
            summary = first.get("summary", "")[:120]
            title = f"New {category} tip"
            body = summary
            if len(new_tips) > 1:
                body += f" (+{len(new_tips) - 1} more)"
            await notifier.notify(title, body)
    else:
        logger.info("No tips generated")

    if config.calendar_ics_enabled:
        try:
            from hypogum.calendar.ics import export_ics
            count = export_ics(memory_store.root, config.data_dir / "calendar.ics")
            logger.info("Exported {} calendar event(s) to calendar.ics", count)
        except Exception as e:
            logger.warning("Calendar ICS export failed: {}", e)

    if config.calendar_view_enabled:
        try:
            from hypogum.calendar.view import export_view
            export_view(
                memory_store.root, memory_store.root,
                today=datetime.date.fromisoformat(local_date),
                tz_label=tz_name,
                png=config.calendar_view_png_enabled,
            )
            logger.info("Calendar view rendered")
        except Exception as e:
            logger.warning("Calendar view render failed: {}", e)

    result = {"summary": summary[:200], "products": products}
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
