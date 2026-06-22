import datetime
import io
import json
import uuid
from pathlib import Path
from typing import ClassVar

from PIL import Image
from loguru import logger

from hypogum.agent.observers.base import Observer
from hypogum.agent.utils.image_dedup import dhash, hamming_distance


class ScreenObserver(Observer):
    """Captures the primary monitor using mss and persists as JPEG."""

    source_type: ClassVar[str] = "screen"
    default_interval: ClassVar[int] = 60

    def __init__(
        self, window_detector=None, *, interval: int | None = None,
        dedup_enabled: bool = True, dedup_threshold: int = 10,
        dedup_hash_size: int = 16,
    ):
        super().__init__(interval=interval)
        self._window_detector = window_detector
        self._dedup_enabled = dedup_enabled
        self._dedup_threshold = dedup_threshold
        self._dedup_hash_size = dedup_hash_size
        self._prev_hash: int | None = None

    async def _load_prev_hash_from_db(self, db, user_id: str, data_dir: Path) -> int | None:
        """Seed the dedup baseline from the last stored screen image (e.g. after a restart)."""
        try:
            latest = await db.get_latest_observation(user_id, self.source_type)
            if not latest or not latest.get("image_path"):
                return None
            path = data_dir / latest["image_path"]
            if not path.exists():
                return None
            with Image.open(path) as img:
                prev = dhash(img.convert("RGB"), self._dedup_hash_size)
            logger.info(
                "[ScreenObserver] seeded dedup hash from last stored observation (id={})",
                latest.get("id"),
            )
            return prev
        except Exception as e:
            logger.debug("[ScreenObserver] could not seed prev hash from db: {}", e)
            return None

    async def observe(
        self, db, user_id: str, data_dir: Path, *,
        max_width: int = 1920, quality: int = 85,
    ) -> int | None:
        try:
            import mss

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            if img.width > max_width:
                ratio = max_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_width, new_h), Image.LANCZOS)

            current_hash = dhash(img, self._dedup_hash_size) if self._dedup_enabled else None
            if self._dedup_enabled and self._prev_hash is None:
                self._prev_hash = await self._load_prev_hash_from_db(db, user_id, data_dir)
            if (
                self._dedup_enabled
                and self._prev_hash is not None
                and current_hash is not None
            ):
                distance = hamming_distance(current_hash, self._prev_hash)
                if distance <= self._dedup_threshold:
                    logger.info(
                        "[ScreenObserver] discarded near-duplicate (hamming={} <= {})",
                        distance, self._dedup_threshold,
                    )
                    return None

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            image_bytes = buf.getvalue()

            now = datetime.datetime.now(datetime.timezone.utc)
            timestamp_str = now.isoformat()
            date_str = timestamp_str[:10]
            safe_ts = timestamp_str.replace(":", "-").replace("T", "_")
            stem = f"screen_{safe_ts}_{uuid.uuid4().hex[:6]}"

            artifacts_dir = data_dir / "observations" / date_str / "artifacts"
            entries_dir = data_dir / "observations" / date_str / "entries"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            entries_dir.mkdir(parents=True, exist_ok=True)

            artifact_path = artifacts_dir / f"{stem}.jpg"
            artifact_path.write_bytes(image_bytes)

            window_titles: list[str] = []
            if self._window_detector:
                try:
                    window_titles = await self._window_detector.get_active_windows()
                    window_titles = window_titles[:50]
                except Exception as e:
                    logger.debug("Window detection skipped: {}", e)

            if window_titles:
                win_list = "\n  ".join(window_titles)
                prompt_text = f"[Screenshot {date_str}] Open windows:\n  {win_list}"
            else:
                prompt_text = f"[Screenshot {date_str}]"

            entry = {
                "type": "screen",
                "observer": "screen",
                "timestamp": timestamp_str,
                "windows": window_titles,
                "prompt_text": prompt_text,
                "artifact_path": f"../artifacts/{stem}.jpg",
            }
            entry_path = entries_dir / f"{stem}.json"
            entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

            db_image_path = f"observations/{date_str}/artifacts/{stem}.jpg"
            obs_id = await db.save_observation(
                user_id, "screen", db_image_path, timestamp_str,
            )
            if self._dedup_enabled:
                self._prev_hash = current_hash
            logger.info("[ScreenObserver] captured {} ({} windows, id={})",
                        stem, len(window_titles), obs_id)
            return obs_id

        except ImportError:
            logger.error("[ScreenObserver] mss and pillow are required: pip install mss pillow")
            return None
        except Exception as e:
            logger.exception("[ScreenObserver] capture failed: {}", e)
            return None
