from fastapi import Depends, FastAPI, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from hypogum.db.auth.base import AuthContext, AuthProvider
from hypogum.db.relational.base import DBStore


def create_db_app(
    db: DBStore,
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

    @app.get("/api/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.on_event("startup")
    async def startup():
        await db.init()
        logger.info("hypogum-db ready")

    @app.on_event("shutdown")
    async def shutdown():
        await db.close()

    return app


def run_db_service(host: str = "0.0.0.0", port: int = 8055, *, db: DBStore,
                   auth: AuthProvider):
    import uvicorn
    app = create_db_app(db, auth)
    uvicorn.run(app, host=host, port=port)
