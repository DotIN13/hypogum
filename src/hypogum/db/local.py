import asyncio
import json
import os
from datetime import timezone as tz
import datetime

import aiosqlite
from loguru import logger

from hypogum.db.base import DBStore


class LocalDBStore(DBStore):
    """Async SQLite data store — direct file access."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT 'Default User',
                settings    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                email       TEXT UNIQUE,
                password_hash TEXT,
                email_verified INTEGER DEFAULT 0,
                verification_code TEXT,
                verification_expires TEXT,
                updated_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS user_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT NOT NULL,
                activity_summary TEXT NOT NULL,
                raw_transcripts  TEXT,
                context          TEXT,
                user_id          TEXT REFERENCES users(id),
                proactive_tip    TEXT
            );
            CREATE TABLE IF NOT EXISTS observations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT NOT NULL,
                image_path  TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                processed   INTEGER DEFAULT 0,
                user_id     TEXT REFERENCES users(id)
            );
        """)
        await self._conn.commit()
        await self._ensure_user()
        logger.info("LocalDBStore ready at {}", self._path)

    async def _ensure_user(self) -> None:
        async with self._write_lock:
            cursor = await self._conn.execute("SELECT COUNT(*) FROM users WHERE id = 'default'")
            row = await cursor.fetchone()
            if row and row[0] == 0:
                now = datetime.datetime.now(tz.utc).isoformat()
                await self._conn.execute(
                    "INSERT INTO users (id, name, settings, created_at) VALUES (?, ?, ?, ?)",
                    ("default", "Default User", "{}", now),
                )
                await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── observations ──────────────────────────

    async def save_observation(self, user_id: str, obs_type: str, image_path: str,
                               timestamp: str, window_titles: list[str] | None = None) -> int:
        async with self._write_lock:
            cursor = await self._conn.execute(
                "INSERT INTO observations (type, image_path, timestamp, processed, user_id) "
                "VALUES (?, ?, ?, 0, ?)",
                (obs_type, image_path, timestamp, user_id),
            )
            await self._conn.commit()
            return cursor.lastrowid

    async def get_pending_observations(self, user_id: str, limit: int = 20) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT id, type, image_path, timestamp "
            "FROM observations WHERE processed = 0 AND user_id = ? "
            "ORDER BY id ASC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_observations_processed(self, user_id: str, obs_ids: list[int]) -> None:
        if not obs_ids:
            return
        async with self._write_lock:
            placeholders = ",".join(["?" for _ in obs_ids])
            await self._conn.execute(
                f"UPDATE observations SET processed = 1 "
                f"WHERE user_id = ? AND id IN ({placeholders})",
                [user_id, *obs_ids],
            )
            await self._conn.commit()

    async def get_observation(self, user_id: str, obs_id: int) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT id, type, image_path, timestamp, processed "
            "FROM observations WHERE id = ? AND user_id = ?",
            (obs_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── events ────────────────────────────────

    async def save_event(self, user_id: str, timestamp: str, summary: str,
                         transcripts: str, context: str) -> int:
        async with self._write_lock:
            cursor = await self._conn.execute(
                "INSERT INTO user_events (timestamp, activity_summary, raw_transcripts, "
                "context, user_id) VALUES (?, ?, ?, ?, ?)",
                (timestamp, summary, transcripts, context, user_id),
            )
            await self._conn.commit()
            return cursor.lastrowid

    async def get_events(self, user_id: str, limit: int = 15, offset: int = 0) -> tuple[list[dict], int]:
        count_cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM user_events WHERE user_id = ?", (user_id,),
        )
        total = (await count_cursor.fetchone())[0]
        cursor = await self._conn.execute(
            "SELECT id, timestamp, activity_summary, raw_transcripts, context, proactive_tip "
            "FROM user_events WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows], total

    async def get_event(self, user_id: str, event_id: int) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT id, timestamp, activity_summary, raw_transcripts, context, proactive_tip "
            "FROM user_events WHERE id = ? AND user_id = ?",
            (event_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_event_tip(self, user_id: str, event_id: int, tip_json: str) -> None:
        async with self._write_lock:
            await self._conn.execute(
                "UPDATE user_events SET proactive_tip = ? WHERE id = ? AND user_id = ?",
                (tip_json, event_id, user_id),
            )
            await self._conn.commit()

    async def get_tips(self, user_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM user_events WHERE user_id = ? "
            "AND proactive_tip IS NOT NULL",
            (user_id,),
        )
        total = (await cursor.fetchone())[0]
        cursor = await self._conn.execute(
            "SELECT id, timestamp, activity_summary, proactive_tip "
            "FROM user_events WHERE user_id = ? AND proactive_tip IS NOT NULL "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows], total
