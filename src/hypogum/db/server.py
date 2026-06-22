import json
from fastapi import FastAPI, HTTPException, Request, Query, Depends
from pydantic import BaseModel
from loguru import logger

from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore
from hypogum.db.auth.base import AuthProvider, AuthContext


def create_db_app(
    db: DBStore,
    vec: VectorStore,
    auth: AuthProvider,
) -> FastAPI:
    """Build the FastAPI `hypogum db` service with /api/v1/ endpoints."""

    app = FastAPI(title="hypogum-db", version="0.1.0")

    # ── models ─────────────────────────────────

    class SaveObservationReq(BaseModel):
        type: str
        image_path: str
        timestamp: str
        window_titles: list[str] | None = None

    class MarkProcessedReq(BaseModel):
        ids: list[int]

    class SaveEventReq(BaseModel):
        timestamp: str
        summary: str
        transcripts: str
        context: str

    class UpdateTipReq(BaseModel):
        tip: str

    class VectorSearchReq(BaseModel):
        embedding: list[float]
        limit: int = 10
        item_type: str | None = None
        exclude_type: str | None = None

    class VectorSimilarReq(BaseModel):
        embedding: list[float]
        item_type: str
        threshold: float = 0.85
        limit: int = 5

    class VectorAddReq(BaseModel):
        records: list[dict]

    class VectorUpdateMetaReq(BaseModel):
        metadata: dict

    # ── auth dependency ────────────────────────

    async def _get_auth(request: Request) -> AuthContext:
        return await auth.authenticate(request)

    # ── observations ───────────────────────────

    @app.post("/api/v1/observations")
    async def save_observation(req: SaveObservationReq, ctx: AuthContext = Depends(_get_auth)):
        obs_id = await db.save_observation(
            ctx.user_id, req.type, req.image_path, req.timestamp, req.window_titles,
        )
        return {"id": obs_id}

    @app.get("/api/v1/observations/pending")
    async def get_pending_observations(limit: int = Query(20), ctx: AuthContext = Depends(_get_auth)):
        items = await db.get_pending_observations(ctx.user_id, limit)
        return {"items": items}

    @app.get("/api/v1/observations/latest")
    async def get_latest_observation(type: str | None = Query(None),
                                     ctx: AuthContext = Depends(_get_auth)):
        item = await db.get_latest_observation(ctx.user_id, type)
        return {"item": item}

    @app.post("/api/v1/observations/processed")
    async def mark_observations_processed(req: MarkProcessedReq, ctx: AuthContext = Depends(_get_auth)):
        await db.mark_observations_processed(ctx.user_id, req.ids)
        return {"status": "ok"}

    @app.get("/api/v1/observations/{obs_id}")
    async def get_observation(obs_id: int, ctx: AuthContext = Depends(_get_auth)):
        item = await db.get_observation(ctx.user_id, obs_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Observation not found")
        return {"item": item}

    # ── events ────────────────────────────────

    @app.post("/api/v1/events")
    async def save_event(req: SaveEventReq, ctx: AuthContext = Depends(_get_auth)):
        event_id = await db.save_event(
            ctx.user_id, req.timestamp, req.summary, req.transcripts, req.context,
        )
        return {"id": event_id}

    @app.get("/api/v1/events")
    async def get_events(limit: int = Query(15), offset: int = Query(0),
                         ctx: AuthContext = Depends(_get_auth)):
        items, total = await db.get_events(ctx.user_id, limit, offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/events/{event_id}")
    async def get_event(event_id: int, ctx: AuthContext = Depends(_get_auth)):
        item = await db.get_event(ctx.user_id, event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"item": item}

    @app.patch("/api/v1/events/{event_id}/tip")
    async def update_event_tip(event_id: int, req: UpdateTipReq,
                               ctx: AuthContext = Depends(_get_auth)):
        await db.update_event_tip(ctx.user_id, event_id, req.tip)
        return {"status": "ok"}

    @app.get("/api/v1/tips")
    async def get_tips(limit: int = Query(50), offset: int = Query(0),
                       ctx: AuthContext = Depends(_get_auth)):
        items, total = await db.get_tips(ctx.user_id, limit, offset)
        return {"items": items, "total": total}

    # ── vectors ───────────────────────────────

    @app.post("/api/v1/vectors/search")
    async def vector_search(req: VectorSearchReq, ctx: AuthContext = Depends(_get_auth)):
        items = await vec.search(
            ctx.user_id, req.embedding,
            limit=req.limit, item_type=req.item_type, exclude_type=req.exclude_type,
        )
        return {"items": items}

    @app.post("/api/v1/vectors/similar")
    async def vector_similar(req: VectorSimilarReq, ctx: AuthContext = Depends(_get_auth)):
        best, best_sim, candidates = await vec.find_similar(
            ctx.user_id, req.embedding, req.item_type, req.threshold, req.limit,
        )
        return {
            "best_match": best,
            "best_similarity": best_sim,
            "candidates": [(c[0], c[1]) for c in candidates],
        }

    @app.post("/api/v1/vectors")
    async def vector_add(req: VectorAddReq, ctx: AuthContext = Depends(_get_auth)):
        await vec.add(ctx.user_id, req.records)
        return {"status": "ok"}

    @app.patch("/api/v1/vectors/{item_id}/metadata")
    async def vector_update_metadata(item_id: str, req: VectorUpdateMetaReq,
                                     ctx: AuthContext = Depends(_get_auth)):
        await vec.update_metadata(ctx.user_id, item_id, req.metadata)
        return {"status": "ok"}

    @app.get("/api/v1/vectors/all")
    async def vector_get_all(item_type: str | None = Query(None),
                             limit: int = Query(50), offset: int = Query(0),
                             ctx: AuthContext = Depends(_get_auth)):
        items, total = await vec.get_all(ctx.user_id, item_type=item_type, limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.on_event("startup")
    async def startup():
        await db.init()
        await vec.init()
        logger.info("hypogum-db ready")

    @app.on_event("shutdown")
    async def shutdown():
        await db.close()

    return app


def run_db_service(host: str = "0.0.0.0", port: int = 8055, *, db: DBStore,
                   vec: VectorStore, auth: AuthProvider):
    import uvicorn
    app = create_db_app(db, vec, auth)
    uvicorn.run(app, host=host, port=port)
