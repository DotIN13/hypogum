import json
import os
from fastapi import FastAPI, HTTPException, Request, Query
from pydantic import BaseModel
from loguru import logger

from hypogum.db.local import LocalDBStore
from hypogum.vector.local import LocalVectorStore
from hypogum.auth.base import AuthProvider, AuthContext


def create_store_app(
    db: LocalDBStore,
    vec: LocalVectorStore,
    auth: AuthProvider,
) -> FastAPI:
    """Build the FastAPI store HTTP server with /api/v1/ endpoints."""

    app = FastAPI(title="hypogum-store", version="0.1.0")

    # ── models ─────────────────────────────────

    class SaveObservationReq(BaseModel):
        user_id: str
        type: str
        image_path: str
        timestamp: str
        window_titles: list[str] | None = None

    class MarkProcessedReq(BaseModel):
        user_id: str
        ids: list[int]

    class SaveEventReq(BaseModel):
        user_id: str
        timestamp: str
        summary: str
        transcripts: str
        context: str

    class UpdateTipReq(BaseModel):
        user_id: str
        tip: str

    class VectorSearchReq(BaseModel):
        user_id: str
        embedding: list[float]
        limit: int = 10
        item_type: str | None = None
        exclude_type: str | None = None

    class VectorSimilarReq(BaseModel):
        user_id: str
        embedding: list[float]
        item_type: str
        threshold: float = 0.85
        limit: int = 5

    class VectorAddReq(BaseModel):
        user_id: str
        records: list[dict]

    class VectorUpdateMetaReq(BaseModel):
        user_id: str
        metadata: dict

    # ── auth dependency ────────────────────────

    async def _get_auth(request: Request) -> AuthContext:
        return await auth.authenticate(request)

    # ── observations ───────────────────────────

    @app.post("/api/v1/observations")
    async def save_observation(req: SaveObservationReq, ctx: AuthContext = None):
        required_user = req.user_id or (ctx.user_id if ctx else "default")
        obs_id = await db.save_observation(
            required_user, req.type, req.image_path, req.timestamp, req.window_titles,
        )
        return {"id": obs_id}

    @app.get("/api/v1/observations/pending")
    async def get_pending_observations(user_id: str = Query(...), limit: int = Query(20)):
        items = await db.get_pending_observations(user_id, limit)
        return {"items": items}

    @app.post("/api/v1/observations/processed")
    async def mark_observations_processed(req: MarkProcessedReq):
        await db.mark_observations_processed(req.user_id, req.ids)
        return {"status": "ok"}

    @app.get("/api/v1/observations/{obs_id}")
    async def get_observation(obs_id: int, user_id: str = Query(...)):
        item = await db.get_observation(user_id, obs_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Observation not found")
        return {"item": item}

    # ── events ────────────────────────────────

    @app.post("/api/v1/events")
    async def save_event(req: SaveEventReq):
        event_id = await db.save_event(
            req.user_id, req.timestamp, req.summary, req.transcripts, req.context,
        )
        return {"id": event_id}

    @app.get("/api/v1/events")
    async def get_events(user_id: str = Query(...), limit: int = Query(15), offset: int = Query(0)):
        items, total = await db.get_events(user_id, limit, offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/events/{event_id}")
    async def get_event(event_id: int, user_id: str = Query(...)):
        item = await db.get_event(user_id, event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"item": item}

    @app.patch("/api/v1/events/{event_id}/tip")
    async def update_event_tip(event_id: int, req: UpdateTipReq):
        await db.update_event_tip(req.user_id, event_id, req.tip)
        return {"status": "ok"}

    @app.get("/api/v1/tips")
    async def get_tips(user_id: str = Query(...), limit: int = Query(50), offset: int = Query(0)):
        items, total = await db.get_tips(user_id, limit, offset)
        return {"items": items, "total": total}

    # ── vectors ───────────────────────────────

    @app.post("/api/v1/vectors/search")
    async def vector_search(req: VectorSearchReq):
        items = await vec.search(
            req.user_id, req.embedding,
            limit=req.limit, item_type=req.item_type, exclude_type=req.exclude_type,
        )
        return {"items": items}

    @app.post("/api/v1/vectors/similar")
    async def vector_similar(req: VectorSimilarReq):
        best, best_sim, candidates = await vec.find_similar(
            req.user_id, req.embedding, req.item_type, req.threshold, req.limit,
        )
        return {
            "best_match": best,
            "best_similarity": best_sim,
            "candidates": [(c[0], c[1]) for c in candidates],
        }

    @app.post("/api/v1/vectors")
    async def vector_add(req: VectorAddReq):
        await vec.add(req.user_id, req.records)
        return {"status": "ok"}

    @app.patch("/api/v1/vectors/{item_id}/metadata")
    async def vector_update_metadata(item_id: str, req: VectorUpdateMetaReq):
        await vec.update_metadata(req.user_id, item_id, req.metadata)
        return {"status": "ok"}

    @app.get("/api/v1/vectors/all")
    async def vector_get_all(user_id: str = Query(...), item_type: str | None = Query(None),
                             limit: int = Query(50), offset: int = Query(0)):
        items, total = await vec.get_all(user_id, item_type=item_type, limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.on_event("startup")
    async def startup():
        await db.init()
        await vec.init()
        logger.info("hypogum-store ready")

    @app.on_event("shutdown")
    async def shutdown():
        await db.close()

    return app


def run_store(host: str = "0.0.0.0", port: int = 8000, *, db: LocalDBStore,
              vec: LocalVectorStore, auth: AuthProvider):
    import uvicorn
    app = create_store_app(db, vec, auth)
    uvicorn.run(app, host=host, port=port)
