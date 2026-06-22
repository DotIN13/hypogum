import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from loguru import logger


@dataclass(slots=True)
class ObserverCapture:
    source_type: str
    timestamp: str
    image_bytes: bytes
    window_titles: list[str] | None = None


class Observer(ABC):
    """Captures from a source (screen/camera) and persists to DBStore."""
    source_type: ClassVar[str]
    default_interval: ClassVar[int] = 60

    def __init__(self, *, interval: int | None = None):
        self.interval = interval if interval is not None else self.default_interval

    @abstractmethod
    async def observe(
        self, db, user_id: str, data_dir: Path, *,
        max_width: int = 1920, quality: int = 85,
    ) -> int | None:
        """Capture → save JPEG → db.save_observation() → return obs_id."""
        ...

    async def run_loop(
        self, db, user_id: str, data_dir: Path, *,
        max_width: int = 1920, quality: int = 85,
        stop_event: asyncio.Event,
        pause_gate=None,
    ):
        """Capture immediately, then every `self.interval` seconds until stop_event is set.

        When `pause_gate` reports paused (system locked/idle), the capture is skipped
        for that tick while the timer keeps running.
        """
        if not (pause_gate and await pause_gate.is_paused()):
            await self._safe_observe(db, user_id, data_dir,
                                     max_width=max_width, quality=quality)
        while not stop_event.is_set():
            try:
                async with asyncio.timeout(self.interval):
                    await stop_event.wait()
                break
            except TimeoutError:
                if pause_gate and await pause_gate.is_paused():
                    continue
                await self._safe_observe(db, user_id, data_dir,
                                         max_width=max_width, quality=quality)

    async def _safe_observe(self, db, user_id: str, data_dir: Path, *,
                            max_width: int, quality: int) -> int | None:
        """Run a single observe() guarded so a failure logs a full traceback
        without killing the observer loop."""
        try:
            return await self.observe(db, user_id, data_dir,
                                      max_width=max_width, quality=quality)
        except Exception as e:
            logger.exception("[{}] observe iteration failed: {}", self.source_type, e)
            return None
