import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


@dataclass
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
    ):
        """Capture immediately, then every `self.interval` seconds until stop_event is set."""
        await self.observe(db, user_id, data_dir,
                           max_width=max_width, quality=quality)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                await self.observe(db, user_id, data_dir,
                                   max_width=max_width, quality=quality)
