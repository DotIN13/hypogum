import asyncio

from loguru import logger

from hypogum.config import Config
from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore
from hypogum.llm.base import LLMProvider
from hypogum.agent.observers.base import Observer
from hypogum.agent.utils.notifier import Notifier
from hypogum.agent.utils.activity_detector import PauseGate
from hypogum.agent.processor.pipeline import run_processing_loop


async def run_agent(
    config: Config,
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    observers: list[Observer],
    notifier: Notifier | None = None,
    pause_gate: PauseGate | None = None,
) -> None:
    """Main background agent loop: spawns observer tasks + processing loop."""

    user_id = config.user_id
    stop_event = asyncio.Event()
    data_dir = config.data_dir

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
        run_processing_loop(db, vec, llm, user_id, config, stop_event, notifier,
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
