import datetime
import json
from pathlib import Path

from loguru import logger

from hypogum.agent.prompts import render_prompt
from hypogum.config import local_iso, to_local_iso, tz_label
from hypogum.db.relational.base import DBStore
from hypogum.llm.base import LLMProvider

_YAML_INDICATORS = set("[]{}>|*&!%@`\"'")


def _artifact_to_entry(image_path: str) -> str:
    return image_path.replace("/artifacts/", "/entries/").rsplit(".", 1)[0] + ".json"


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    needs_quote = (
        s == ""
        or s != s.strip()
        or s[0] in _YAML_INDICATORS
        or s[0] in "#,"
        or ": " in s
        or " #" in s
    )
    return json.dumps(s, ensure_ascii=False) if needs_quote else s


def _frontmatter(meta: dict) -> str:
    """Render a YAML frontmatter block from scalar/list values (no external dep)."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            rendered = ", ".join(_yaml_scalar(v) for v in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n"


async def _load_and_cap_observations(
    db: DBStore, user_id: str, max_artifacts: int,
    types: tuple[str, ...] | None = None,
) -> list[dict] | None:
    rows = await db.get_pending_observations(user_id, limit=max_artifacts + 30)
    if types is not None:
        rows = [r for r in rows if r.get("type") in types]
    if not rows:
        return None

    if len(rows) > max_artifacts:
        skipped = rows[:-max_artifacts]
        skipped_ids = [r["id"] for r in skipped]
        await db.mark_observations_processed(user_id, skipped_ids)
        logger.info(
            "Skipped {} older observations (cap={})", len(skipped), max_artifacts,
        )
        rows = rows[-max_artifacts:]

    logger.info(
        "Describing {} pending observations for user {}...", len(rows), user_id[:8],
    )
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

    windows = sorted(all_windows)
    windows_section = ""
    if windows:
        win_list = "\n  ".join(windows)
        windows_section = f"\n\nOpen windows visible in the screenshots:\n  {win_list}"

    return image_paths, active_window_section, windows_section, active_window, windows


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


def _capture_span(
    rows: list[dict], tz_name: str | None,
) -> tuple[str | None, str | None]:
    """Earliest/latest observation capture time (DB-UTC) as offset-aware local ISO."""
    caps = sorted(r["timestamp"] for r in rows if r.get("timestamp"))
    if not caps:
        return None, None
    return to_local_iso(caps[0], tz_name), to_local_iso(caps[-1], tz_name)


def _save_product(
    data_dir: Path, timestamp_utc: str, body: str, *,
    prefix: str = "screen", frontmatter: dict | None = None,
) -> str:
    """Write a product under its UTC capture-date folder; frontmatter is local."""
    date_str = timestamp_utc[:10]
    products_dir = data_dir / "observations" / date_str / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    safe_ts = timestamp_utc.replace(":", "-").replace("T", "_")
    product_path = products_dir / f"{prefix}_{safe_ts}.md"
    content = (_frontmatter(frontmatter) + body) if frontmatter else body
    product_path.write_text(content, encoding="utf-8")
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
    tz_name: str | None = None,
) -> str | None:
    """Load pending screen observations, call LLM for rich description,
    save as a product markdown file with frontmatter. Returns the path or None."""

    rows = await _load_and_cap_observations(
        db, user_id, max_artifacts, types=("screen", "camera"),
    )
    if not rows:
        return None

    (image_paths, active_window_section, windows_section,
     active_window, windows) = _collect_observation_context(rows, data_dir)

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

    description = (
        response.get("text", "") if isinstance(response, dict) else str(response)
    )
    if not description:
        description = response.get("raw", str(response))
    if not description:
        logger.warning("Empty description from LLM")
        return None

    obs_ids = [r["id"] for r in rows]
    await db.mark_observations_processed(user_id, obs_ids)

    timestamp_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    first_capture, last_capture = _capture_span(rows, tz_name)
    meta = {
        "type": "screen",
        "created": local_iso(tz_name),
        "tz": tz_label(tz_name),
        "observation_count": len(rows),
        "observation_ids": obs_ids,
        "first_capture": first_capture,
        "last_capture": last_capture,
        "active_window": active_window,
        "window_count": len(windows),
        "windows": windows or None,
    }
    product_path = _save_product(
        data_dir, timestamp_utc, description, prefix="screen", frontmatter=meta,
    )

    logger.info(
        "[describe] generated product: {} ({} chars)", product_path, len(description),
    )
    return product_path


async def describe_pending_user_input(
    user_id: str,
    db: DBStore,
    *,
    data_dir: Path,
    max_notes: int = 50,
    tz_name: str | None = None,
) -> str | None:
    """Turn pending user_input observations into a single user_* product.

    The note text is passed through (lightly framed) — the ingest agent parses it
    into calendar event frontmatter. Returns the relative product path or None.
    """
    rows = await _load_and_cap_observations(
        db, user_id, max_notes, types=("user_input",),
    )
    if not rows:
        return None

    sections: list[str] = []
    source_files: list[str] = []
    for i, row in enumerate(rows, 1):
        note_abs = data_dir / row["image_path"]
        try:
            note = note_abs.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("[describe] user-input note not found: {}", note_abs)
            note = ""
        if not note:
            continue
        entry_abs = data_dir / _artifact_to_entry(row["image_path"])
        if entry_abs.exists():
            try:
                raw = entry_abs.read_text(encoding="utf-8")
                sf = json.loads(raw).get("source_file")
                if sf:
                    source_files.append(sf)
            except (OSError, json.JSONDecodeError):
                pass
        when = to_local_iso(row.get("timestamp", ""), tz_name)
        sections.append(f"## Note {i} [{when}]\n\n{note}")

    if not sections:
        await db.mark_observations_processed(user_id, [r["id"] for r in rows])
        return None

    body = (
        "# User-reported notes\n\n"
        "These were submitted by the user (directly, via MCP, or a backend call). "
        "Treat them as source: user calendar events — planned (future) or actual "
        "(reported past activity); recurring phrasing means one series + RRULE.\n\n"
        + "\n\n".join(sections)
        + "\n"
    )

    obs_ids = [r["id"] for r in rows]
    await db.mark_observations_processed(user_id, obs_ids)

    timestamp_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    first_capture, last_capture = _capture_span(rows, tz_name)
    meta = {
        "type": "user_input",
        "created": local_iso(tz_name),
        "tz": tz_label(tz_name),
        "note_count": len(sections),
        "observation_ids": obs_ids,
        "first_capture": first_capture,
        "last_capture": last_capture,
        "source_files": source_files or None,
    }
    product_path = _save_product(
        data_dir, timestamp_utc, body, prefix="user", frontmatter=meta,
    )

    logger.info(
        "[describe] generated user-input product: {} ({} notes)",
        product_path, len(sections),
    )
    return product_path
