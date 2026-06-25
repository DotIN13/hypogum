"""HTTP db provider used by the agent (and MCP) to reach the standalone `hypogum db` service.

The agent never opens the relational DB directly; it always talks to the
`hypogum db` service over HTTP via this client.
"""

from hypogum.db.relational.base import DBStore


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


__all__ = ["RemoteDBStore"]
