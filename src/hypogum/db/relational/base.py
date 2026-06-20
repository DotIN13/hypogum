from abc import ABC, abstractmethod


class DBStore(ABC):
    """Abstract relational data store (SQLite-backed). Every method scoped by user_id."""

    # ── observations ──────────────────────────

    @abstractmethod
    async def save_observation(self, user_id: str, obs_type: str, image_path: str,
                               timestamp: str, window_titles: list[str] | None = None) -> int:
        """Persist an observation record. Returns the row id."""
        ...

    @abstractmethod
    async def get_pending_observations(self, user_id: str, limit: int = 20) -> list[dict]:
        """Return unprocessed observations (oldest first), capped at limit."""
        ...

    @abstractmethod
    async def mark_observations_processed(self, user_id: str, obs_ids: list[int]) -> None:
        """Mark a batch of observation ids as processed."""
        ...

    @abstractmethod
    async def get_observation(self, user_id: str, obs_id: int) -> dict | None:
        """Return a single observation by id."""
        ...

    # ── events ────────────────────────────────

    @abstractmethod
    async def save_event(self, user_id: str, timestamp: str, summary: str,
                         transcripts: str, context: str) -> int:
        """Persist an analysis event. Returns the row id."""
        ...

    @abstractmethod
    async def get_events(self, user_id: str, limit: int = 15, offset: int = 0) -> tuple[list[dict], int]:
        """Return paginated analysis events (newest first). Returns (items, total)."""
        ...

    @abstractmethod
    async def get_event(self, user_id: str, event_id: int) -> dict | None:
        """Return a single event by id."""
        ...

    @abstractmethod
    async def update_event_tip(self, user_id: str, event_id: int, tip_json: str) -> None:
        """Attach generated tip JSON to an event."""
        ...

    @abstractmethod
    async def get_tips(self, user_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """Return paginated events that have a tip. Returns (items, total)."""
        ...
