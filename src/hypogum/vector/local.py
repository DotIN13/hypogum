import asyncio

import chromadb
from chromadb import ClientAPI, Collection
from loguru import logger

from hypogum.vector.base import VectorStore


class LocalVectorStore(VectorStore):
    """ChromaDB vector store backed by persistent on-disk database."""

    def __init__(self, chroma_path: str):
        self._path = chroma_path
        self._client: ClientAPI | None = None
        self._write_lock = asyncio.Lock()
        self._collections: dict[str, Collection] = {}
        self._default_collection: Collection | None = None

    async def init(self) -> None:
        if self._client is not None:
            return
        logger.info("LocalVectorStore: connecting persistent {}", self._path)
        self._client = chromadb.PersistentClient(path=self._path)
        try:
            self._default_collection = self._client.get_collection("events")
        except Exception:
            self._default_collection = self._client.create_collection("events")
        logger.info("LocalVectorStore: ready ({} items)", self._default_collection.count())

    async def _ensure_collection(self, user_id: str) -> Collection:
        await self.init()
        if user_id == "default" or not user_id:
            assert self._default_collection is not None
            return self._default_collection
        if user_id not in self._collections:
            coll_name = f"events_{user_id}"
            try:
                assert self._client is not None
                self._collections[user_id] = self._client.get_collection(coll_name)
            except Exception:
                assert self._client is not None
                self._collections[user_id] = self._client.create_collection(coll_name)
        return self._collections[user_id]

    async def search(self, user_id: str, embedding: list[float], *,
                     limit: int = 10, item_type: str | None = None,
                     exclude_type: str | None = None) -> list[dict]:
        await self.init()
        coll = await self._ensure_collection(user_id)

        conditions: list[dict] = [{"user_id": user_id}]
        if item_type:
            conditions.append({"type": item_type})
        if exclude_type:
            conditions.append({"type": {"$ne": exclude_type}})
        where: dict = conditions[0] if len(conditions) == 1 else {"$and": conditions}

        results = coll.query(
            query_embeddings=[embedding],
            n_results=limit,
            where=where,
            include=["metadatas", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        out = []
        for i, m in enumerate(metadatas):
            d = dict(m) if m else {}
            if i < len(ids):
                d["id"] = ids[i]
            if i < len(distances):
                d["similarity"] = round(1.0 - distances[i], 4)
            out.append(d)
        return out

    async def find_similar(self, user_id: str, embedding: list[float],
                           item_type: str, threshold: float = 0.85, limit: int = 5
                           ) -> tuple[dict | None, float, list[tuple[dict, float]]]:
        await self.init()
        coll = await self._ensure_collection(user_id)

        results = coll.query(
            query_embeddings=[embedding],
            n_results=limit,
            where={"$and": [{"user_id": user_id}, {"type": item_type}]},
            include=["metadatas", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        candidates: list[tuple[dict, float]] = []
        best_meta: dict | None = None
        best_sim = 0.0

        for i in range(min(len(ids), len(metadatas), len(distances))):
            sim = 1.0 - distances[i]
            meta = dict(metadatas[i]) if metadatas[i] else {}
            meta["id"] = ids[i]
            meta["similarity"] = round(sim, 4)
            candidates.append((meta, sim))
            if sim >= threshold and sim > best_sim:
                best_meta = meta
                best_sim = sim

        return best_meta, best_sim, candidates

    async def add(self, user_id: str, records: list[dict]) -> None:
        await self.init()
        coll = await self._ensure_collection(user_id)

        ids = [str(r["id"]) for r in records]
        embeddings = [r["vector"] for r in records]
        metadatas = []
        for r in records:
            if "metadata" in r:
                metadatas.append(r["metadata"])
            else:
                metadatas.append({
                    "timestamp": r.get("timestamp", ""),
                    "user_id": r.get("user_id", user_id),
                })

        async with self._write_lock:
            coll.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
        logger.info("LocalVectorStore: added {} items", len(records))

    async def update_metadata(self, user_id: str, item_id: str, metadata: dict) -> None:
        await self.init()
        coll = await self._ensure_collection(user_id)
        async with self._write_lock:
            coll.update(ids=[item_id], metadatas=[metadata])
        logger.debug("LocalVectorStore: updated metadata for {}", item_id)

    async def get_all(self, user_id: str, *,
                      item_type: str | None = None,
                      limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        await self.init()
        coll = await self._ensure_collection(user_id)

        conditions: list[dict] = [{"user_id": user_id}]
        if item_type:
            conditions.append({"type": item_type})
        where: dict = conditions[0] if len(conditions) == 1 else {"$and": conditions}

        try:
            raw = coll.get(where=where, include=["metadatas"])
        except Exception:
            return [], 0

        ids = raw.get("ids", [])
        metas = raw.get("metadatas", [])
        items: list[dict] = []
        for i, m in enumerate(metas):
            d = dict(m) if m else {}
            if i < len(ids):
                d["id"] = ids[i]
            items.append(d)

        total = len(items)
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        page = items[offset:offset + limit]
        return page, total
