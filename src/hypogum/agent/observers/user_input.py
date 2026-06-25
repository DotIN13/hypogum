import datetime
import json
import shutil
import uuid
from pathlib import Path
from typing import ClassVar

from loguru import logger

from hypogum.agent.observers.base import Observer
from hypogum.agent.processor.describe import describe_pending_user_input


class UserInputObserver(Observer):
    """Treats user-submitted notes as observations.

    Notes (``.md`` / ``.txt``) dropped into the inbox by the user, an MCP tool, or a
    backend call are persisted as ``user_input`` observations; the describe step
    turns pending ones into a ``user_*`` product that the ingest agent reads and
    converts into ``source: user`` calendar events.
    """

    source_type: ClassVar[str] = "user_input"
    default_interval: ClassVar[int] = 60

    def __init__(self, inbox_dir: Path, *, interval: int | None = None):
        super().__init__(interval=interval)
        self._inbox_dir = Path(inbox_dir)

    async def observe(
        self, db, user_id: str, data_dir: Path, *,
        max_width: int = 1920, quality: int = 85,
    ) -> int | None:
        try:
            self._inbox_dir.mkdir(parents=True, exist_ok=True)
            consumed_dir = self._inbox_dir / ".consumed"

            notes = sorted(
                p for p in self._inbox_dir.iterdir()
                if p.is_file() and p.suffix.lower() in (".md", ".txt")
            )
            if not notes:
                return None

            last_obs_id: int | None = None
            for note_path in notes:
                try:
                    text = note_path.read_text(encoding="utf-8").strip()
                except OSError as e:
                    logger.warning(
                        "[UserInputObserver] could not read {}: {}", note_path, e,
                    )
                    continue

                now = datetime.datetime.now(datetime.UTC)
                timestamp_str = now.isoformat()
                date_str = timestamp_str[:10]
                safe_ts = timestamp_str.replace(":", "-").replace("T", "_")
                stem = f"user_{safe_ts}_{uuid.uuid4().hex[:6]}"

                artifacts_dir = data_dir / "observations" / date_str / "artifacts"
                entries_dir = data_dir / "observations" / date_str / "entries"
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                entries_dir.mkdir(parents=True, exist_ok=True)

                artifact_path = artifacts_dir / f"{stem}.md"
                artifact_path.write_text(text, encoding="utf-8")

                entry = {
                    "type": "user_input",
                    "observer": "user_input",
                    "timestamp": timestamp_str,
                    "source_file": note_path.name,
                    "artifact_path": f"../artifacts/{stem}.md",
                }
                (entries_dir / f"{stem}.json").write_text(
                    json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8",
                )

                db_path = f"observations/{date_str}/artifacts/{stem}.md"
                last_obs_id = await db.save_observation(
                    user_id, "user_input", db_path, timestamp_str,
                )

                consumed_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(note_path), str(consumed_dir / note_path.name))
                logger.info(
                    "[UserInputObserver] ingested note {} (id={})",
                    note_path.name, last_obs_id,
                )

            return last_obs_id

        except Exception as e:
            logger.exception("[UserInputObserver] observe failed: {}", e)
            return None

    async def describe(
        self, db, user_id: str, data_dir: Path, *,
        llm=None, prompts_dir: Path | None = None, tz_name: str | None = None,
    ) -> str | None:
        return await describe_pending_user_input(
            user_id, db, data_dir=data_dir, tz_name=tz_name,
        )
