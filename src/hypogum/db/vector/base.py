from abc import ABC, abstractmethod


class VectorStore(ABC):
    """Abstract vector database store (ChromaDB-backed). Every method scoped by user_id."""

    @abstractmethod
    async def search(self, user_id: str, embedding: list[float], *,
                     limit: int = 10, item_type: str | None = None,
                     exclude_type: str | None = None) -> list[dict]:
        """Semantic search returning items with metadata, id, and similarity score."""
        ...

    @abstractmethod
    async def find_similar(self, user_id: str, embedding: list[float],
                           item_type: str, threshold: float = 0.85, limit: int = 5
                           ) -> tuple[dict | None, float, list[tuple[dict, float]]]:
        """Find the best match above threshold. Returns (best_meta, best_sim, all_candidates)."""
        ...

    @abstractmethod
    async def add(self, user_id: str, records: list[dict]) -> None:
        """Bulk insert vector records. Each record: {id, vector, metadata}."""
        ...

    @abstractmethod
    async def update_metadata(self, user_id: str, item_id: str, metadata: dict) -> None:
        """Update metadata for an existing item (no re-embedding)."""
        ...

    @abstractmethod
    async def get_all(self, user_id: str, *,
                      item_type: str | None = None,
                      limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """List all items for a user. Returns (items, total_count)."""
        ...
