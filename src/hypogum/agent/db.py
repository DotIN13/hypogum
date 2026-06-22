"""HTTP db provider used by the agent (and MCP) to reach the standalone `hypogum db` service.

The agent never opens the relational DB or ChromaDB directly; it always talks to the
`hypogum db` service over HTTP via these clients.
"""

from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore


class _HTTPClientMixin:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")
        self._client: object | None = None  # httpx.AsyncClient — lazy import

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def _ensure_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def _get(self, path: str, **params) -> dict:
        await self._ensure_client()
        r = await self._client.get(f"/api/v1{path}", params=params, headers=self._headers())  # type: ignore[union-attr]
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, data: dict) -> dict:
        await self._ensure_client()
        r = await self._client.post(f"/api/v1{path}", json=data, headers=self._headers())  # type: ignore[union-attr]
        r.raise_for_status()
        return r.json()

    async def _patch(self, path: str, data: dict) -> dict:
        await self._ensure_client()
        r = await self._client.patch(f"/api/v1{path}", json=data, headers=self._headers())  # type: ignore[union-attr]
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()  # type: ignore[union-attr]


class RemoteDBStore(_HTTPClientMixin, DBStore):
    """Async HTTP client delegating relational ops to a remote `hypogum db` service."""

    # ── observations ──────────────────────────

    async def save_observation(self, user_id: str, obs_type: str, image_path: str,
                               timestamp: str, window_titles: list[str] | None = None) -> int:
        result = await self._post("/observations", {
            "type": obs_type,
            "image_path": image_path,
            "timestamp": timestamp,
            "window_titles": window_titles or [],
        })
        return result["id"]

    async def get_pending_observations(self, user_id: str, limit: int = 20) -> list[dict]:
        result = await self._get("/observations/pending", limit=limit)
        return result["items"]

    async def mark_observations_processed(self, user_id: str, obs_ids: list[int]) -> None:
        await self._post("/observations/processed", {"ids": obs_ids})

    async def get_observation(self, user_id: str, obs_id: int) -> dict | None:
        result = await self._get(f"/observations/{obs_id}")
        return result.get("item")

    async def get_latest_observation(self, user_id: str,
                                     obs_type: str | None = None) -> dict | None:
        result = await self._get("/observations/latest", type=obs_type)
        return result.get("item")

    # ── events ────────────────────────────────

    async def save_event(self, user_id: str, timestamp: str, summary: str,
                         transcripts: str, context: str) -> int:
        result = await self._post("/events", {
            "timestamp": timestamp,
            "summary": summary,
            "transcripts": transcripts,
            "context": context,
        })
        return result["id"]

    async def get_events(self, user_id: str, limit: int = 15, offset: int = 0) -> tuple[list[dict], int]:
        result = await self._get("/events", limit=limit, offset=offset)
        return result["items"], result["total"]

    async def get_event(self, user_id: str, event_id: int) -> dict | None:
        result = await self._get(f"/events/{event_id}")
        return result.get("item")

    async def update_event_tip(self, user_id: str, event_id: int, tip_json: str) -> None:
        await self._patch(f"/events/{event_id}/tip", {"tip": tip_json})

    async def get_tips(self, user_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        result = await self._get("/tips", limit=limit, offset=offset)
        return result["items"], result["total"]


class RemoteVectorStore(_HTTPClientMixin, VectorStore):
    """Async HTTP client delegating vector ops to a remote `hypogum db` service."""

    async def search(self, user_id: str, embedding: list[float], *,
                     limit: int = 10, item_type: str | None = None,
                     exclude_type: str | None = None) -> list[dict]:
        result = await self._post("/vectors/search", {
            "embedding": embedding,
            "limit": limit,
            "item_type": item_type,
            "exclude_type": exclude_type,
        })
        return result["items"]

    async def find_similar(self, user_id: str, embedding: list[float],
                           item_type: str, threshold: float = 0.85, limit: int = 5
                           ) -> tuple[dict | None, float, list[tuple[dict, float]]]:
        result = await self._post("/vectors/similar", {
            "embedding": embedding,
            "item_type": item_type,
            "threshold": threshold,
            "limit": limit,
        })
        best = result.get("best_match")
        best_sim = result.get("best_similarity", 0.0)
        candidates = [(c[0], c[1]) for c in result.get("candidates", [])]
        return best, best_sim, candidates

    async def add(self, user_id: str, records: list[dict]) -> None:
        await self._post("/vectors", {"records": records})

    async def update_metadata(self, user_id: str, item_id: str, metadata: dict) -> None:
        await self._patch(f"/vectors/{item_id}/metadata", {"metadata": metadata})

    async def get_all(self, user_id: str, *,
                      item_type: str | None = None,
                      limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        result = await self._get("/vectors/all",
                                 item_type=item_type, limit=limit, offset=offset)
        return result["items"], result["total"]


__all__ = ["RemoteDBStore", "RemoteVectorStore"]
