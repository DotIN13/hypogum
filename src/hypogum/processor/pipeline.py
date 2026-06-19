import asyncio
import json

from loguru import logger

from hypogum.config import Config
from hypogum.db.base import DBStore
from hypogum.vector.base import VectorStore
from hypogum.llm.base import LLMProvider
from hypogum.utils.notifier import Notifier
from hypogum.processor.analyzer import process_pending_observations
from hypogum.processor.tips import generate_proactive_tip


async def run_processing_cycle(
    user_id: str,
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    *,
    prompts_dir,
    data_dir,
    confidence_threshold: int,
    merge_threshold: float,
    max_artifacts: int,
    max_evidence_entries: int = 10,
    max_tip_goals: int = 5,
    max_tip_events: int = 5,
    max_tip_traits: int = 20,
    tip_summary_chars: int = 1000,
    trait_similarity_threshold: float = 0.5,
) -> tuple[dict | None, dict | None]:
    """One full processing cycle: analyze → save event → add vectors → generate tips → save tip.

    Returns (result, tip_data). result is the pipeline result dict with event_id,
    tip_data is the raw tip JSON (for notification). Both can be None."""
    result = await process_pending_observations(
        user_id, db, vec, llm,
        prompts_dir=prompts_dir,
        data_dir=data_dir,
        confidence_threshold=confidence_threshold,
        merge_threshold=merge_threshold,
        max_artifacts=max_artifacts,
        max_evidence_entries=max_evidence_entries,
    )
    if not result:
        return None, None

    event_id = await db.save_event(
        user_id,
        result["timestamp"],
        result["summary"],
        result["raw_transcripts"],
        result["analysis_data"],
    )

    items = result.get("items", [])
    if items:
        for item in items:
            item["metadata"]["user_event_id"] = str(event_id)
        await vec.add(user_id, items)
        logger.info("Indexed {} items into vector DB", len(items))

    analysis = json.loads(result.get("analysis_data", "{}"))
    tip_data = await generate_proactive_tip(
        user_id, db, vec, llm,
        prompts_dir=prompts_dir,
        data_dir=data_dir,
        current_events=analysis.get("events", []),
        current_timestamp=result.get("timestamp"),
        current_summary=analysis.get("summary", ""),
        latest_observation=result.get("latest_screen_observation"),
        latest_screen_image_path=result.get("latest_screen_image_path"),
        max_goals=max_tip_goals,
        max_events=max_tip_events,
        max_traits=max_tip_traits,
        max_summary_chars=tip_summary_chars,
        trait_similarity_threshold=trait_similarity_threshold,
    )

    if tip_data and tip_data.get("tips"):
        await db.update_event_tip(
            user_id, event_id,
            json.dumps(tip_data, ensure_ascii=False),
        )
        logger.info("Stored proactive tip for event {}", event_id)

    result["event_id"] = event_id
    return result, tip_data


async def run_processing_loop(
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    user_id: str,
    config: Config,
    stop_event: asyncio.Event,
    notifier: Notifier | None = None,
) -> None:
    """Run processing cycles on interval until stop_event is set."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.process_interval)
            break
        except asyncio.TimeoutError:
            try:
                result, tip_data = await run_processing_cycle(
                    user_id, db, vec, llm,
                    prompts_dir=config.prompts_dir,
                    data_dir=config.data_dir,
                    confidence_threshold=config.confidence_threshold,
                    merge_threshold=config.merge_threshold,
                    max_artifacts=config.max_artifacts,
                    max_evidence_entries=config.max_evidence_entries,
                    max_tip_goals=config.max_tip_goals,
                    max_tip_events=config.max_tip_events,
                    max_tip_traits=config.max_tip_traits,
                    tip_summary_chars=config.tip_summary_chars,
                    trait_similarity_threshold=config.trait_similarity_threshold,
                )
                if result:
                    logger.info("Saved event: {}", result["summary"][:100])
                else:
                    logger.debug("No pending observations to process")

                if tip_data and tip_data.get("tips") and config.notify_on_tips and notifier:
                    tips = tip_data["tips"]
                    first = tips[0]
                    title = f"Tip for: {first.get('goal', 'you')[:50]}"
                    body = first.get("tip_summary", "")[:120]
                    if len(tips) > 1:
                        body += f" (+{len(tips) - 1} more)"
                    await notifier.notify(title, body)
            except Exception as e:
                logger.error("Process cycle failed: {}", e)
