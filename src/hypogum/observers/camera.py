import io
import datetime
import json
import uuid
from pathlib import Path
from typing import ClassVar

from PIL import Image
from loguru import logger

from hypogum.observers.base import Observer


class CameraObserver(Observer):
    """Captures a webcam frame using OpenCV and persists as JPEG."""
    source_type: ClassVar[str] = "camera"
    default_interval: ClassVar[int] = 120

    async def observe(
        self, db, user_id: str, data_dir: Path, *,
        max_width: int = 1920, quality: int = 85,
    ) -> int | None:
        try:
            import cv2

            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                logger.warning("[CameraObserver] no camera available")
                return None

            ret, frame = cap.read()
            cap.release()

            if not ret:
                logger.warning("[CameraObserver] failed to read frame")
                return None

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)

            if img.width > max_width:
                ratio = max_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_width, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            image_bytes = buf.getvalue()

            now = datetime.datetime.now(datetime.timezone.utc)
            timestamp_str = now.isoformat()
            date_str = timestamp_str[:10]
            safe_ts = timestamp_str.replace(":", "-").replace("T", "_")
            stem = f"camera_{safe_ts}_{uuid.uuid4().hex[:6]}"

            artifacts_dir = data_dir / "observations" / date_str / "artifacts"
            entries_dir = data_dir / "observations" / date_str / "entries"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            entries_dir.mkdir(parents=True, exist_ok=True)

            artifact_path = artifacts_dir / f"{stem}.jpg"
            artifact_path.write_bytes(image_bytes)

            entry = {
                "type": "camera",
                "observer": "camera",
                "timestamp": timestamp_str,
                "windows": [],
                "prompt_text": f"[Camera {date_str}]",
                "artifact_path": f"../artifacts/{stem}.jpg",
            }
            entry_path = entries_dir / f"{stem}.json"
            entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

            db_image_path = f"observations/{date_str}/artifacts/{stem}.jpg"
            obs_id = await db.save_observation(
                user_id, "camera", db_image_path, timestamp_str,
            )
            logger.info("[CameraObserver] captured {} (id={})", stem, obs_id)
            return obs_id

        except ImportError:
            logger.error("[CameraObserver] opencv-python and pillow are required: pip install opencv-python pillow")
            return None
        except Exception as e:
            logger.error("[CameraObserver] capture failed: {}", e)
            return None
