import json
from pathlib import Path

from loguru import logger

from hypogum.agent.prompts import render_prompt
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider
from hypogum.memory.search import search_memory
from hypogum.memory.store import MemoryStore


def _load_proactive_schema(prompts_dir: Path) -> dict:
    return json.loads((prompts_dir / "proactive_schema.json").read_text(encoding="utf-8"))


def _format_observation_section(latest_observation: dict | None) -> str:
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


def _read_relevant_pages(memory_store: MemoryStore, query: str, max_pages: int = 20) -> list[dict]:
    """Search memory pages for relevant context, read the matching pages."""
    hits = search_memory(query, memory_store.root, max_results=max_pages)
    seen: set[str] = set()
    pages: list[dict] = []
    for hit in hits:
        file_path = hit.get("file", "")
        if file_path in seen:
            continue
        seen.add(file_path)
        try:
            content = memory_store.read_page(file_path)
            pages.append({"path": file_path, "content": content[:2000]})
        except (FileNotFoundError, OSError):
            continue
    return pages


def _format_trait_section(memory_store: MemoryStore, query: str, max_pages: int = 20) -> str:
    """Search for and format relevant trait pages as a prompt section."""
    pages = _read_relevant_pages(memory_store, f"type: trait {query}", max_pages)
    if not pages:
        return "(no matching traits found in memory)"

    lines: list[str] = []
    for p in pages:
        content_preview = p["content"].replace("\n", " ")[:200]
        lines.append(f"- [{p['path']}] {content_preview}")
    return "\n".join(lines) if lines else "(no matching traits found in memory)"


def _format_goal_section(memory_store: MemoryStore, query: str, max_pages: int = 5) -> str:
    """Search for and format relevant goal pages as a prompt section."""
    pages = _read_relevant_pages(memory_store, f"type: goal {query}", max_pages)
    if not pages:
        return "(no stored goals found in memory)"

    lines: list[str] = []
    for p in pages:
        content_preview = p["content"].replace("\n", " ")[:200]
        lines.append(f"- [{p['path']}] {content_preview}")
    return "\n".join(lines) if lines else "(no stored goals found in memory)"


def _format_tip_prompt(
    prompts_dir: Path,
    goals_section: str,
    events_section: str,
    summary_section: str,
    traits_section: str,
    observation_section: str,
) -> str:
    return render_prompt(
        prompts_dir, "proactive_prompt.md",
        goals_section=goals_section,
        events_section=events_section,
        summary_section=summary_section,
        traits_section=traits_section,
        observation_section=observation_section,
    )


def _build_tip_multimodal_parts(
    prompts_dir: Path,
    data_dir: Path,
    prompt: str,
    latest_screen_image_path: str | None,
):
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


async def generate_proactive_tip(
    user_id: str,
    db: DBStore,
    llm: LLMProvider,
    *,
    memory_store: MemoryStore,
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
    """Generate proactive tips using memory pages as context."""

    summary_text = current_summary[:max_summary_chars] if current_summary else ""

    if not summary_text:
        logger.info("No summary; skipping proactive tip.")
        return None

    events_section = f"- [{current_timestamp or 'just now'}] {summary_text[:300]}"

    goals_section = _format_goal_section(memory_store, summary_text, max_goals)

    traits_section = _format_trait_section(memory_store, summary_text, max_traits)

    observation_section = _format_observation_section(latest_observation)

    prompt = _format_tip_prompt(
        prompts_dir,
        goals_section,
        events_section,
        summary_text[:max_summary_chars],
        traits_section,
        observation_section,
    )

    parts, schema = _build_tip_multimodal_parts(
        prompts_dir, data_dir, prompt, latest_screen_image_path,
    )

    try:
        tip_data = await llm.generate(
            system_prompt="", parts=parts, response_schema=schema,
        )
    except json.JSONDecodeError as e:
        logger.warning("Proactive tip response failed schema/JSON validation: {}", e)
        return None
    except Exception as e:
        logger.exception("Error generating proactive tip: {}", e)
        return None

    tip_count = len(tip_data.get("tips", []))
    first_summary = tip_data["tips"][0]["tip_summary"][:80] if tip_data.get("tips") else "(empty)"
    logger.info("Generated {} proactive tip(s), first: {}", tip_count, first_summary)
    return tip_data
