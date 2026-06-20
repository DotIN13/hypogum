from hypogum.db.base import DBStore


class RemoteDBStore(DBStore):
    """Async HTTP client that delegates to a remote hypogum store server."""

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
