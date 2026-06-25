import json
import time
from pathlib import Path

from loguru import logger

from hypogum.agent.prompts import render_prompt
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider


def _artifact_to_entry(image_path: str) -> str:
    return image_path.replace("/artifacts/", "/entries/").rsplit(".", 1)[0] + ".json"


async def _load_and_cap_observations(
    db: DBStore, user_id: str, max_artifacts: int,
) -> list[dict] | None:
    rows = await db.get_pending_observations(user_id, limit=max_artifacts + 10)
    if not rows:
        return None

    if len(rows) > max_artifacts:
        skipped = rows[:-max_artifacts]
        skipped_ids = [r["id"] for r in skipped]
        await db.mark_observations_processed(user_id, skipped_ids)
        logger.info("Skipped {} older observations (cap={})", len(skipped), max_artifacts)
        rows = rows[-max_artifacts:]

    logger.info("Describing {} pending observations for user {}...", len(rows), user_id[:8])
    return rows


def _collect_observation_context(rows: list[dict], data_dir: Path):
    image_paths: list[str] = []
    all_windows: set[str] = set()
    active_window: str | None = None

    for row in rows:
        image_path = row["image_path"]
        image_paths.append(image_path)

        entry_abs = data_dir / _artifact_to_entry(image_path)
        if entry_abs.exists():
            entry_data = json.loads(entry_abs.read_text(encoding="utf-8"))
            if entry_data.get("type") == "screen":
                windows = entry_data.get("windows") or []
                all_windows.update(windows)
                aw = entry_data.get("active_window")
                if aw:
                    active_window = aw

    active_window_section = ""
    if active_window:
        active_window_section = f"\n\nActive (frontmost) window: {active_window}"

    windows_section = ""
    if all_windows:
        win_list = "\n  ".join(sorted(all_windows))
        windows_section = f"\n\nOpen windows visible in the screenshots:\n  {win_list}"

    return image_paths, active_window_section, windows_section


def _build_multimodal_parts(
    prompts_dir: Path, data_dir: Path,
    image_paths: list[str],
    active_window_section: str,
    windows_section: str,
):
    prompt = render_prompt(prompts_dir, "describe_prompt.md",
                           active_window_section=active_window_section,
                           windows_section=windows_section)

    parts: list[dict] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        artifact_abs = data_dir / image_path
        if artifact_abs.exists():
            parts.append({
                "type": "image",
                "data": artifact_abs.read_bytes(),
                "mime_type": "image/jpeg",
            })
        else:
            logger.warning("Artifact not found: {}", artifact_abs)

    return parts


def _save_product(data_dir: Path, timestamp: str, description: str) -> str:
    date_str = timestamp[:10]
    products_dir = data_dir / "observations" / date_str / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    safe_ts = timestamp.replace(":", "-").replace("T", "_")
    product_path = products_dir / f"screen_{safe_ts}.md"
    product_path.write_text(description, encoding="utf-8")
    logger.info("[describe] saved product {}", product_path.relative_to(data_dir))
    return f"observations/{date_str}/products/{product_path.name}"


async def describe_pending_screen_observations(
    user_id: str,
    db: DBStore,
    llm: LLMProvider,
    *,
    prompts_dir: Path,
    data_dir: Path,
    max_artifacts: int = 20,
) -> str | None:
    """Load pending screen observations, call LLM for rich description,
    save as a product markdown file. Returns the relative product path or None."""

    rows = await _load_and_cap_observations(db, user_id, max_artifacts)
    if not rows:
        return None

    image_paths, active_window_section, windows_section = _collect_observation_context(rows, data_dir)

    parts = _build_multimodal_parts(prompts_dir, data_dir, image_paths,
                                    active_window_section, windows_section)

    try:
        response = await llm.generate(
            system_prompt="",
            parts=parts,
            response_schema=None,
        )
    except Exception as e:
        logger.exception("Describe analysis failed: {}", e)
        return None

    description = response.get("text", "") if isinstance(response, dict) else str(response)
    if not description:
        description = response.get("raw", str(response))
    if not description:
        logger.warning("Empty description from LLM")
        return None

    obs_ids = [r["id"] for r in rows]
    await db.mark_observations_processed(user_id, obs_ids)

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    product_path = _save_product(data_dir, timestamp, description)

    logger.info("[describe] generated product: {} ({} chars)", product_path, len(description))
    return product_path
