import asyncio
import datetime
from datetime import timezone as tz

from loguru import logger
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hypogum.db.relational.base import DBStore


def _normalize_dsn(dsn: str) -> str:
    """Map common driverless DSNs onto their async drivers."""
    if dsn.startswith("sqlite:") and not dsn.startswith("sqlite+"):
        return dsn.replace("sqlite:", "sqlite+aiosqlite:", 1)
    if dsn.startswith("postgresql:") and not dsn.startswith("postgresql+"):
        return dsn.replace("postgresql:", "postgresql+asyncpg:", 1)
    if dsn.startswith("postgres:"):
        return dsn.replace("postgres:", "postgresql+asyncpg:", 1)
    if dsn.startswith("mysql:") and not dsn.startswith("mysql+"):
        return dsn.replace("mysql:", "mysql+aiomysql:", 1)
    return dsn


_metadata = MetaData()

users = Table(
    "users", _metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False, server_default="Default User"),
    Column("settings", Text, nullable=False, server_default="{}"),
    Column("created_at", String, nullable=False),
    Column("email", String, unique=True),
    Column("password_hash", String),
    Column("email_verified", Integer, server_default="0"),
    Column("verification_code", String),
    Column("verification_expires", String),
    Column("updated_at", String),
)

user_events = Table(
    "user_events", _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", String, nullable=False),
    Column("activity_summary", Text, nullable=False),
    Column("raw_transcripts", Text),
    Column("context", Text),
    Column("user_id", String, ForeignKey("users.id")),
    Column("proactive_tip", Text),
)

observations = Table(
    "observations", _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("type", String, nullable=False),
    Column("image_path", String, nullable=False),
    Column("timestamp", String, nullable=False),
    Column("processed", Integer, server_default="0"),
    Column("user_id", String, ForeignKey("users.id")),
)


class SQLAlchemyDBStore(DBStore):
    """Relational data store over SQLAlchemy async — local SQLite or remote Postgres/MySQL via DSN."""

    def __init__(self, dsn: str):
        self._dsn = _normalize_dsn(dsn)
        self._engine: AsyncEngine | None = None
        self._write_lock = asyncio.Lock()

    @property
    def is_sqlite(self) -> bool:
        return self._dsn.startswith("sqlite")

    async def init(self) -> None:
        if self._engine is not None:
            return
        self._engine = create_async_engine(self._dsn, future=True)

        if self.is_sqlite:
            from sqlalchemy import event

            @event.listens_for(self._engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver glue
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        async with self._engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)

        await self._ensure_user()
        logger.info("SQLAlchemyDBStore ready ({})", self._dsn)

    async def _ensure_user(self) -> None:
        assert self._engine is not None
        async with self._write_lock:
            async with self._engine.begin() as conn:
                count = await conn.scalar(
                    select(func.count()).select_from(users).where(users.c.id == "default")
                )
                if not count:
                    now = datetime.datetime.now(tz.utc).isoformat()
                    await conn.execute(insert(users).values(
                        id="default", name="Default User", settings="{}", created_at=now,
                    ))

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # ── observations ──────────────────────────

    async def save_observation(self, user_id: str, obs_type: str, image_path: str,
                               timestamp: str, window_titles: list[str] | None = None) -> int:
        assert self._engine is not None
        async with self._write_lock:
            async with self._engine.begin() as conn:
                result = await conn.execute(insert(observations).values(
                    type=obs_type, image_path=image_path, timestamp=timestamp,
                    processed=0, user_id=user_id,
                ))
                return int(result.inserted_primary_key[0])

    async def get_pending_observations(self, user_id: str, limit: int = 20) -> list[dict]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(
                    observations.c.id, observations.c.type,
                    observations.c.image_path, observations.c.timestamp,
                )
                .where(observations.c.processed == 0, observations.c.user_id == user_id)
                .order_by(observations.c.id.asc())
                .limit(limit)
            )
            return [dict(r) for r in result.mappings()]

    async def mark_observations_processed(self, user_id: str, obs_ids: list[int]) -> None:
        if not obs_ids:
            return
        assert self._engine is not None
        async with self._write_lock:
            async with self._engine.begin() as conn:
                await conn.execute(
                    update(observations)
                    .where(observations.c.user_id == user_id,
                           observations.c.id.in_(obs_ids))
                    .values(processed=1)
                )

    async def get_observation(self, user_id: str, obs_id: int) -> dict | None:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(
                    observations.c.id, observations.c.type, observations.c.image_path,
                    observations.c.timestamp, observations.c.processed,
                )
                .where(observations.c.id == obs_id, observations.c.user_id == user_id)
            )
            row = result.mappings().first()
            return dict(row) if row else None

    # ── events ────────────────────────────────

    async def save_event(self, user_id: str, timestamp: str, summary: str,
                         transcripts: str, context: str) -> int:
        assert self._engine is not None
        async with self._write_lock:
            async with self._engine.begin() as conn:
                result = await conn.execute(insert(user_events).values(
                    timestamp=timestamp, activity_summary=summary,
                    raw_transcripts=transcripts, context=context, user_id=user_id,
                ))
                return int(result.inserted_primary_key[0])

    async def get_events(self, user_id: str, limit: int = 15, offset: int = 0) -> tuple[list[dict], int]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            total = await conn.scalar(
                select(func.count()).select_from(user_events).where(user_events.c.user_id == user_id)
            )
            result = await conn.execute(
                select(
                    user_events.c.id, user_events.c.timestamp, user_events.c.activity_summary,
                    user_events.c.raw_transcripts, user_events.c.context, user_events.c.proactive_tip,
                )
                .where(user_events.c.user_id == user_id)
                .order_by(user_events.c.id.desc())
                .limit(limit).offset(offset)
            )
            return [dict(r) for r in result.mappings()], int(total or 0)

    async def get_event(self, user_id: str, event_id: int) -> dict | None:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(
                    user_events.c.id, user_events.c.timestamp, user_events.c.activity_summary,
                    user_events.c.raw_transcripts, user_events.c.context, user_events.c.proactive_tip,
                )
                .where(user_events.c.id == event_id, user_events.c.user_id == user_id)
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def update_event_tip(self, user_id: str, event_id: int, tip_json: str) -> None:
        assert self._engine is not None
        async with self._write_lock:
            async with self._engine.begin() as conn:
                await conn.execute(
                    update(user_events)
                    .where(user_events.c.id == event_id, user_events.c.user_id == user_id)
                    .values(proactive_tip=tip_json)
                )

    async def get_tips(self, user_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        assert self._engine is not None
        async with self._engine.connect() as conn:
            total = await conn.scalar(
                select(func.count()).select_from(user_events).where(
                    user_events.c.user_id == user_id,
                    user_events.c.proactive_tip.isnot(None),
                )
            )
            result = await conn.execute(
                select(
                    user_events.c.id, user_events.c.timestamp,
                    user_events.c.activity_summary, user_events.c.proactive_tip,
                )
                .where(user_events.c.user_id == user_id, user_events.c.proactive_tip.isnot(None))
                .order_by(user_events.c.id.desc())
                .limit(limit).offset(offset)
            )
            return [dict(r) for r in result.mappings()], int(total or 0)
