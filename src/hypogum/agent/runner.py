import asyncio

from loguru import logger

from hypogum.agent.observers.base import Observer
from hypogum.agent.processor.pipeline import run_processing_loop
from hypogum.agent.utils.activity_detector import PauseGate
from hypogum.agent.utils.notifier import Notifier
from hypogum.config import Config
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider
from hypogum.memory.store import MemoryStore


async def run_agent(
    config: Config,
    db: DBStore,
    llm: LLMProvider,
    memory_store: MemoryStore,
    observers: list[Observer],
    notifier: Notifier | None = None,
    pause_gate: PauseGate | None = None,
) -> None:
    """Main background agent loop: spawns observer tasks + processing loop (ingest + tips inline)."""

    user_id = config.user_id
    stop_event = asyncio.Event()
    data_dir = config.data_dir

    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agent.log"
    logger.add(
        log_path,
        level="INFO",
        rotation="10 MB",
        retention="14 days",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )
    logger.info("Agent logs → {}", log_path)

    tasks: list[asyncio.Task] = []
    for obs in observers:
        tasks.append(asyncio.create_task(
            obs.run_loop(db, user_id, data_dir,
                         max_width=config.observe_max_width,
                         quality=config.observe_quality,
                         stop_event=stop_event,
                         pause_gate=pause_gate)
        ))
        logger.info("Started {} observer (every {}s)", obs.source_type, obs.interval)

    tasks.append(asyncio.create_task(
        run_processing_loop(db, llm, user_id, config, stop_event,
                            memory_store=memory_store,
                            observers=observers,
                            notifier=notifier,
                            pause_gate=pause_gate)
    ))

    logger.info("hypogum agent started (user={}, process_interval={}s)",
                user_id, config.process_interval)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        stop_event.set()
    finally:
        stop_event.set()
        for t in tasks:
            if not t.done():
                t.cancel()
