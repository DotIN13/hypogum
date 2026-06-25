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
