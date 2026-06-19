from hypogum.vector.base import VectorStore


class RemoteVectorStore(VectorStore):
    """Async HTTP client that delegates to a remote hypogum vector endpoint."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client: object | None = None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def _ensure_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def _post(self, path: str, data: dict) -> dict:
        await self._ensure_client()
        r = await self._client.post(f"/api/v1{path}", json=data, headers=self._headers())  # type: ignore[union-attr]
        r.raise_for_status()
        return r.json()

    async def _get(self, path: str, **params) -> dict:
        await self._ensure_client()
        r = await self._client.get(f"/api/v1{path}", params=params, headers=self._headers())  # type: ignore[union-attr]
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

    async def search(self, user_id: str, embedding: list[float], *,
                     limit: int = 10, item_type: str | None = None,
                     exclude_type: str | None = None) -> list[dict]:
        result = await self._post("/vectors/search", {
            "user_id": user_id,
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
            "user_id": user_id,
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
        await self._post("/vectors", {"user_id": user_id, "records": records})

    async def update_metadata(self, user_id: str, item_id: str, metadata: dict) -> None:
        await self._patch(f"/vectors/{item_id}/metadata", {"user_id": user_id, "metadata": metadata})

    async def get_all(self, user_id: str, *,
                      item_type: str | None = None,
                      limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        result = await self._get("/vectors/all", user_id=user_id,
                                 item_type=item_type, limit=limit, offset=offset)
        return result["items"], result["total"]
