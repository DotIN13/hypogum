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

    @abstractmethod
    async def get_latest_observation(self, user_id: str,
                                     obs_type: str | None = None) -> dict | None:
        """Return the most recent observation (highest id), optionally filtered by type."""
        ...
