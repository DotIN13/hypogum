import json
from pathlib import Path

from loguru import logger

from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore
from hypogum.llm.base import LLMProvider

_TRAIT_TYPES = {"personality", "skill", "interest", "preference", "ownership", "relationship", "weakness"}


def _load_proactive_prompt(prompts_dir: Path) -> str:
    return (prompts_dir / "proactive_prompt.md").read_text(encoding="utf-8")


def _load_proactive_schema(prompts_dir: Path) -> dict:
    return json.loads((prompts_dir / "proactive_schema.json").read_text(encoding="utf-8"))


async def _find_similar_goals(
    llm: LLMProvider, vec: VectorStore, query: str, user_id: str, limit: int = 5,
) -> list[dict]:
    """Embed the query and search for semantically similar user goals in the vector store."""
    embeddings = await llm.embed([query])
    goals = await vec.search(
        user_id, embeddings[0], limit=limit, item_type="goal",
    )

    lines = [f"[proactive-tip] goals query: \"{query[:120]}\""]
    if goals:
        for g in goals:
            sim = g.get("similarity", 0)
            lines.append(f"  {sim:.2f}  [goal] \"{g.get('content', '')[:80]}\"")
        lines.append(f"  → matched {len(goals)} goals")
    else:
        lines.append("  → no matching goals found")
    logger.info("\n".join(lines))
    return goals


async def _find_similar_traits(
    llm: LLMProvider, vec: VectorStore, query: str, user_id: str,
    limit: int = 20, threshold: float = 0.5,
) -> list[dict]:
    """Embed the query and search for semantically similar personality/skill/interest/etc traits."""
    embeddings = await llm.embed([query])
    traits = await vec.search(
        user_id, embeddings[0], limit=limit, exclude_type="event",
    )

    lines = [f"[proactive-tip] traits query (threshold={threshold}): \"{query[:120]}\""]
    if traits:
        for t in traits:
            sim = t.get("similarity", 0)
            lines.append(f"  {sim:.2f}  [{t.get('type', '?')}] \"{t.get('content', '')[:80]}\"")
        lines.append(f"  → matched {len(traits)} traits")
    else:
        lines.append("  → no matching traits found")
    logger.info("\n".join(lines))

    traits = [r for r in traits
              if r.get("type") in _TRAIT_TYPES
              and r.get("similarity", 0) >= threshold]
    return traits


# ── pipeline phases ───────────────────────────


async def _gather_events(
    vec: VectorStore, user_id: str, current_events: list[dict] | None, limit: int = 5,
) -> list[dict] | None:
    """Use provided events or fetch the most recent ones from vector store.
    Returns None if no events are available."""
    if current_events:
        return current_events
    events, _ = await vec.get_all(user_id, item_type="event", limit=limit)
    return events if events else None


async def _build_prompt_sections(
    llm: LLMProvider,
    vec: VectorStore,
    user_id: str,
    events: list[dict],
    current_timestamp: str | None,
    current_summary: str | None,
    latest_observation: dict | None,
    max_goals: int = 5,
    max_traits: int = 20,
    max_summary_chars: int = 1000,
    trait_similarity_threshold: float = 0.5,
):
    """Search for matching goals and traits, then format all prompt sections.
    Returns a dict with keys: goals, events, summary, traits, observation."""
    event_texts = [e.get('event', e.get('content', str(e))) for e in events]
    search_query = " ".join(event_texts)

    goals = await _find_similar_goals(llm, vec, search_query, user_id, limit=max_goals)

    goals_section = "\n".join(
        f"- {g.get('content', '')} (confidence: {g.get('confidence', '?')}, similarity: {g.get('similarity', 0):.2f})"
        for g in goals
    ) if goals else (
        "(No stored goals found — infer the user's most likely goals from their "
        "current events, screen observation, activity summary, and known traits, "
        "and generate tips for those inferred goals.)"
    )

    now_ts = current_timestamp or "just now"
    events_section = "\n".join(
        f"- [{now_ts}] {e.get('event', e.get('content', str(e)))}"
        for e in events
    )

    summary_section = current_summary[:max_summary_chars] if current_summary else "(no summary available)"
    traits_query = current_summary[:max_summary_chars] if current_summary else " ".join(event_texts)
    traits = await _find_similar_traits(llm, vec, traits_query, user_id, limit=max_traits, threshold=trait_similarity_threshold)
    traits_section = "\n".join(
        f"- [{t.get('type', '?')}] {t.get('content', '')} (similarity: {t.get('similarity', 0):.2f})"
        for t in traits
    ) if traits else "(no matching traits found)"

    observation_section = _format_observation_section(latest_observation)

    return {
        "goals": goals_section,
        "goals_raw": goals,
        "events": events_section,
        "summary": summary_section,
        "traits": traits_section,
        "observation": observation_section,
    }


def _format_observation_section(latest_observation: dict | None) -> str:
    """Build the observation section string from window titles and prompt text."""
    if not latest_observation:
        return "(no observation details)"

    obs_parts = []
    windows = latest_observation.get("windows") or []
    if windows:
        obs_parts.append("Open windows:\n  " + "\n  ".join(windows))
    prompt_text = latest_observation.get("prompt_text", "")
    if prompt_text:
        obs_parts.append(prompt_text)

    return "\n".join(obs_parts) if obs_parts else "(no observation details)"


def _format_tip_prompt(
    prompts_dir: Path,
    goals_section: str,
    events_section: str,
    summary_section: str,
    traits_section: str,
    observation_section: str,
) -> str:
    """Load the proactive prompt template and inject all formatted sections."""
    try:
        return _load_proactive_prompt(prompts_dir).format(
            goals_section=goals_section,
            events_section=events_section,
            summary_section=summary_section,
            traits_section=traits_section,
            observation_section=observation_section,
        )
    except KeyError:
        template = _load_proactive_prompt(prompts_dir)
        for placeholder, value in [
            ("{goals_section}", goals_section),
            ("{events_section}", events_section),
            ("{summary_section}", summary_section),
            ("{traits_section}", traits_section),
            ("{observation_section}", observation_section),
        ]:
            template = template.replace(placeholder, value)
        return template


def _build_tip_multimodal_parts(
    prompts_dir: Path,
    data_dir: Path,
    prompt: str,
    latest_screen_image_path: str | None,
):
    """Build the multimodal parts list: attach latest screenshot if available, then the prompt.
    Returns (parts, schema)."""
    schema = _load_proactive_schema(prompts_dir)

    parts: list[dict] = []
    if latest_screen_image_path:
        image_abs = data_dir / latest_screen_image_path
        if image_abs.exists():
            parts.append({"type": "text", "text": "Here is the latest screenshot of the user's screen:"})
            parts.append({
                "type": "image",
                "data": image_abs.read_bytes(),
                "mime_type": "image/jpeg",
            })
            logger.info("Attached latest screenshot to proactive tip prompt")
        else:
            logger.warning("Latest screen image not found: {}", image_abs)
    parts.append({"type": "text", "text": prompt})

    return parts, schema


# ── public API ────────────────────────────────


async def generate_proactive_tip(
    user_id: str,
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    *,
    prompts_dir: Path,
    data_dir: Path,
    current_events: list[dict] | None = None,
    current_timestamp: str | None = None,
    current_summary: str | None = None,
    latest_observation: dict | None = None,
    latest_screen_image_path: str | None = None,
    max_goals: int = 5,
    max_events: int = 5,
    max_traits: int = 20,
    max_summary_chars: int = 1000,
    trait_similarity_threshold: float = 0.5,
) -> dict | None:
    """Generate proactive tips by matching goals and traits against current activity."""

    events = await _gather_events(vec, user_id, current_events, limit=max_events)
    if not events:
        logger.info("No events found; skipping proactive tip.")
        return None

    sections = await _build_prompt_sections(
        llm, vec, user_id, events, current_timestamp, current_summary, latest_observation,
        max_goals=max_goals, max_traits=max_traits,
        max_summary_chars=max_summary_chars, trait_similarity_threshold=trait_similarity_threshold,
    )

    if not sections["goals_raw"]:
        logger.info("No relevant goals found; asking LLM to infer goals from current activity.")

    prompt = _format_tip_prompt(
        prompts_dir,
        sections["goals"],
        sections["events"],
        sections["summary"],
        sections["traits"],
        sections["observation"],
    )

    parts, schema = _build_tip_multimodal_parts(
        prompts_dir, data_dir, prompt, latest_screen_image_path,
    )

    try:
        tip_data = await llm.generate(
            system_prompt="", parts=parts, response_schema=schema,
        )
    except json.JSONDecodeError as e:
        logger.error("Failed to parse proactive tip JSON: {}", e)
        return None
    except Exception as e:
        logger.error("Error generating proactive tip: {}", e)
        return None

    tip_count = len(tip_data.get("tips", []))
    first_summary = tip_data["tips"][0]["tip_summary"][:80] if tip_data.get("tips") else "(empty)"
    logger.info("Generated {} proactive tip(s), first: {}", tip_count, first_summary)
    return tip_data
