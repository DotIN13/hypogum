import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore
from hypogum.llm.base import LLMProvider

_CATEGORIES = [
    "events", "personalities", "skills", "interests",
    "preferences", "ownerships", "relationships", "weaknesses",
]


def _wrap_evidence(evidence_text: str, timestamp: str) -> str:
    """Wrap a raw evidence string into a JSON array with a single timestamped entry."""
    return json.dumps(
        [{"text": evidence_text, "timestamp": timestamp}],
        ensure_ascii=False,
    )


def _merge_evidence(existing_json: str | None, new_json: str, max_entries: int = 10) -> str:
    """Merge existing and new evidence JSON arrays, capping at max_entries entries."""
    existing = []
    if existing_json:
        try:
            parsed = json.loads(existing_json)
            if isinstance(parsed, list):
                existing = parsed
            else:
                existing = [{"text": str(parsed), "timestamp": ""}]
        except (json.JSONDecodeError, TypeError):
            logger.debug("Discarding unparseable existing evidence JSON")

    try:
        new_entries = json.loads(new_json)
        if not isinstance(new_entries, list):
            new_entries = [{"text": str(new_entries), "timestamp": ""}]
    except (json.JSONDecodeError, TypeError):
        logger.debug("New evidence JSON unparseable; wrapping as plain text")
        new_entries = [{"text": str(new_json), "timestamp": ""}]

    merged = existing + new_entries
    if len(merged) > max_entries:
        merged = merged[-max_entries:]
    return json.dumps(merged, ensure_ascii=False)


@dataclass(slots=True)
class _ItemEntry:
    """A single analysis item from the LLM response, ready for embedding and ingestion.
    category is the plural array key (e.g. 'personalities'),
    content_key is the singular dict key (e.g. 'personality')."""
    category: str
    index: int
    item: dict

    @property
    def content_key(self) -> str:
        return self.category.rstrip("s")

    @property
    def content_text(self) -> str:
        return self.item.get(self.content_key, "").strip()

    @property
    def confidence(self) -> int:
        return self.item.get("confidence", 0)

    @property
    def evidence(self) -> str:
        return self.item.get("evidence", "")

    @property
    def lifespan(self) -> int:
        return self.item.get("lifespan", 0)


def _build_item_record(entry: _ItemEntry, event_id: int, timestamp: str, user_id: str) -> dict:
    """Build a ChromaDB-ready item record with metadata from an _ItemEntry."""
    return {
        "id": f"{entry.category}_{entry.index}_{uuid.uuid4().hex[:8]}",
        "vector": None,
        "category": entry.category,
        "index": entry.index,
        "metadata": {
            "type": entry.content_key,
            "content": f"{entry.content_key}: {entry.content_text}",
            "timestamp": timestamp,
            "user_id": user_id,
            "user_event_id": str(event_id),
            "confidence": entry.confidence,
            "evidence": entry.evidence,
            "lifespan": entry.lifespan,
        },
    }


def _load_analysis_prompt(prompts_dir: Path) -> str:
    return (prompts_dir / "analysis_prompt.md").read_text(encoding="utf-8")


def _load_analysis_schema(prompts_dir: Path) -> dict:
    return json.loads((prompts_dir / "analysis_schema.json").read_text(encoding="utf-8"))


def _artifact_to_entry(image_path: str) -> str:
    return image_path.replace("/artifacts/", "/entries/").rsplit(".", 1)[0] + ".json"


# ── pipeline phases ───────────────────────────


async def _load_and_cap_observations(
    db: DBStore, user_id: str, max_artifacts: int,
) -> list[dict] | None:
    """Fetch unprocessed observations, cap at max_artifacts, mark overflow as processed.
    Returns None if no observations are pending."""
    rows = await db.get_pending_observations(user_id, limit=max_artifacts + 10)
    if not rows:
        return None

    if len(rows) > max_artifacts:
        skipped = rows[:-max_artifacts]
        skipped_ids = [r["id"] for r in skipped]
        await db.mark_observations_processed(user_id, skipped_ids)
        logger.info("Skipped {} older observations (cap={})", len(skipped), max_artifacts)
        rows = rows[-max_artifacts:]

    logger.info("Processing {} pending observations for user {}...", len(rows), user_id[:8])
    return rows


def _collect_observation_context(rows: list[dict], data_dir: Path):
    """Scan observation entry JSONs for image paths, window titles, and latest screen capture.
    Returns (image_paths, windows_section, latest_screen_entry, latest_screen_image_path)."""
    image_paths: list[str] = []
    all_windows: set[str] = set()
    latest_screen_entry: dict | None = None
    latest_screen_image_path: str | None = None

    for row in rows:
        image_path = row["image_path"]
        image_paths.append(image_path)

        entry_abs = data_dir / _artifact_to_entry(image_path)
        if entry_abs.exists():
            entry_data = json.loads(entry_abs.read_text(encoding="utf-8"))
            if entry_data.get("type") == "screen":
                windows = entry_data.get("windows") or []
                all_windows.update(windows)
                latest_screen_entry = entry_data
                latest_screen_image_path = image_path

    windows_section = ""
    if all_windows:
        win_list = "\n  ".join(sorted(all_windows))
        windows_section = f"\n\nOpen windows visible in the screenshots:\n  {win_list}"

    return image_paths, windows_section, latest_screen_entry, latest_screen_image_path


def _build_multimodal_parts(
    prompts_dir: Path, data_dir: Path,
    image_paths: list[str], windows_section: str,
):
    """Format the analysis prompt with window context and build multimodal parts list.
    Returns (parts, schema)."""
    try:
        prompt = _load_analysis_prompt(prompts_dir).format(windows_section=windows_section)
    except KeyError:
        prompt = _load_analysis_prompt(prompts_dir).replace("{windows_section}", windows_section)

    schema = _load_analysis_schema(prompts_dir)

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

    return parts, schema


async def _extract_and_embed_entries(
    analysis: dict, llm: LLMProvider, confidence_threshold: int,
) -> tuple[list[_ItemEntry], list[list[float]]]:
    """Wrap raw evidence, filter items by confidence threshold, and embed item texts.
    Returns (entries, embeddings)."""
    analysis_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for cat in _CATEGORIES:
        for item in analysis.get(cat, []):
            evidence_text = item.get("evidence", "")
            if evidence_text and not evidence_text.startswith("["):
                item["evidence"] = _wrap_evidence(evidence_text, analysis_ts)

    entries: list[_ItemEntry] = []
    for cat in _CATEGORIES:
        items = analysis.get(cat, [])
        for i, item in enumerate(items):
            entry = _ItemEntry(category=cat, index=i, item=item)
            if entry.confidence >= confidence_threshold and entry.content_text:
                entries.append(entry)

    logger.info("Extracted {} items across {} categories",
                 len(entries), len({e.category for e in entries}))

    item_texts = [e.content_text for e in entries]
    items_embeds = await llm.embed(item_texts) if item_texts else []
    return entries, items_embeds


async def _build_and_deduplicate_records(
    entries: list[_ItemEntry],
    items_embeds: list[list[float]],
    analysis: dict,
    timestamp: str,
    user_id: str,
    vec: VectorStore,
    merge_threshold: float,
    max_evidence_entries: int = 10,
) -> tuple[list[dict], dict]:
    """Build ChromaDB item records from entries + embeddings, then deduplicate
    against existing vector items by cosine similarity. Events are never merged.
    Returns (item_records, updated_analysis_dict)."""
    item_records = []
    for entry, embed_vec in zip(entries, items_embeds):
        if embed_vec:
            rec = _build_item_record(entry, 0, timestamp, user_id)
            rec["vector"] = embed_vec
            item_records.append(rec)

    merged_count = 0
    deduped_records = []
    for rec in item_records:
        meta = rec["metadata"]
        if meta["type"] == "event":
            deduped_records.append(rec)
            continue

        existing, sim, candidates = await vec.find_similar(
            user_id, rec["vector"], meta["type"], merge_threshold,
        )

        _log_dedup(meta, merge_threshold, candidates, existing, sim)

        if existing:
            merged_evidence = _merge_evidence(
                existing.get("evidence", ""), meta.get("evidence", ""), max_evidence_entries,
            )
            merged_meta = {
                **existing,
                "type": meta["type"],
                "content": meta.get("content", existing.get("content", "")),
                "confidence": max(meta.get("confidence", 0), existing.get("confidence", 0)),
                "lifespan": max(meta.get("lifespan", 0), existing.get("lifespan", 0)),
                "evidence": merged_evidence,
                "timestamp": existing.get("timestamp", meta["timestamp"]),
            }
            await vec.update_metadata(user_id, existing["id"], merged_meta)
            merged_count += 1

            cat = rec.get("category", "")
            idx = rec.get("index", 0)
            cat_items = analysis.get(cat, [])
            if idx < len(cat_items):
                cat_items[idx]["evidence"] = merged_evidence
        else:
            deduped_records.append(rec)

    if merged_count:
        logger.info("Merged {} similar propositions", merged_count)
        item_records = deduped_records

    return item_records, analysis


def _log_dedup(meta: dict, threshold: float,
               candidates: list[tuple[dict, float]],
               existing: dict | None, sim: float):
    target = meta.get("content", "")
    lines = [f"[{meta['type']}] \"{target[:80]}\""]
    if candidates:
        lines.append(f"  threshold={threshold}")
        for c, s in candidates:
            mark = "  ✓" if (existing and c.get("id") == existing.get("id")) else "   "
            lines.append(f"  {s:.2f}{mark} \"{c.get('content', '')[:70]}\"")
    if existing:
        lines.append(f"  → merged into \"{existing.get('content', '')[:70]}\"")
    else:
        lines.append(f"  → no match (best={sim:.2f})")
    logger.info("\n".join(lines))


# ── public API ────────────────────────────────


async def process_pending_observations(
    user_id: str,
    db: DBStore,
    vec: VectorStore,
    llm: LLMProvider,
    *,
    prompts_dir: Path,
    data_dir: Path,
    confidence_threshold: int = 5,
    merge_threshold: float = 0.85,
    max_artifacts: int = 20,
    max_evidence_entries: int = 10,
) -> dict | None:
    """Process unprocessed observations: load → analyze → embed → deduplicate."""

    rows = await _load_and_cap_observations(db, user_id, max_artifacts)
    if not rows:
        return None

    image_paths, windows_section, latest_screen_entry, latest_screen_image_path = \
        _collect_observation_context(rows, data_dir)

    parts, schema = _build_multimodal_parts(
        prompts_dir, data_dir, image_paths, windows_section,
    )

    try:
        analysis = await llm.generate(
            system_prompt="", parts=parts, response_schema=schema,
        )
    except json.JSONDecodeError as e:
        logger.warning("LLM analysis response failed schema/JSON validation: {}", e)
        return None
    except Exception as e:
        logger.exception("Error during analysis: {}", e)
        return None

    summary = analysis.get("summary", "")
    logger.info("Generated summary: {}", summary[:120])

    entries, items_embeds = await _extract_and_embed_entries(
        analysis, llm, confidence_threshold,
    )

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_transcripts = str([Path(p).name for p in image_paths])

    obs_ids = [r["id"] for r in rows]
    await db.mark_observations_processed(user_id, obs_ids)

    item_records, analysis = await _build_and_deduplicate_records(
        entries, items_embeds, analysis, timestamp, user_id, vec, merge_threshold, max_evidence_entries,
    )

    return {
        "timestamp": timestamp,
        "summary": summary,
        "analysis_data": json.dumps(analysis, ensure_ascii=False),
        "raw_transcripts": raw_transcripts,
        "items": item_records,
        "latest_screen_observation": latest_screen_entry,
        "latest_screen_image_path": latest_screen_image_path,
    }
