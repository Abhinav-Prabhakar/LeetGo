"""Async SQLite persistence with schema versioning and legacy migration."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from .errors import UsernameTakenError
from .models import Cohort, UserRecord

logger = logging.getLogger("LeetGo.database")

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS cohorts (
    cohort_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    guild_id INTEGER,
    channel_id INTEGER,
    host_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (guild_id, name)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE,
    discord_username TEXT,
    lc_username TEXT NOT NULL COLLATE NOCASE,
    cohort_id INTEGER REFERENCES cohorts(cohort_id) ON DELETE SET NULL,
    roadmap TEXT,
    roadmap_progress TEXT NOT NULL DEFAULT '[]',
    goal_questions INTEGER,
    goal_duration INTEGER,
    goal_start_date TEXT,
    goal_baseline INTEGER,
    reminder_hour INTEGER,
    reminder_minute INTEGER,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS idx_users_lc_username ON users(lc_username COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_users_cohort ON users(cohort_id);
CREATE INDEX IF NOT EXISTS idx_cohorts_guild ON cohorts(guild_id);

CREATE TABLE IF NOT EXISTS reminder_log (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    sent_on TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, sent_on)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """A small async repository around a single SQLite connection."""

    def __init__(self, path: Path | str = "data/leetgo.db") -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Open the database, apply pragmas and run migrations."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._adopt_legacy_storage()
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._migrate()
        await self._conn.commit()
        logger.info("Database ready at %s", self.path)

    def _adopt_legacy_storage(self) -> None:
        """Copy a v2-era ``storage.db`` into the new default location on first run."""
        if self.path.exists():
            return
        candidates = (Path("storage.db"), self.path.parent / "storage.db")
        for candidate in candidates:
            if candidate.exists() and candidate.resolve() != self.path.resolve():
                shutil.copy2(candidate, self.path)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(f"{candidate}{suffix}")
                    if sidecar.exists():
                        shutil.copy2(sidecar, Path(f"{self.path}{suffix}"))
                logger.warning("Imported legacy database %s into %s", candidate, self.path)
                return

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        """Return the live connection or raise a clear error."""
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def health_check(self) -> bool:
        """Return whether the database answers a trivial query."""
        try:
            cursor = await self.conn.execute("SELECT 1")
            row = await cursor.fetchone()
            return bool(row and row[0] == 1)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Database health check failed")
            return False

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------
    async def _table_exists(self, name: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return await cursor.fetchone() is not None

    async def _columns(self, table: str) -> set[str]:
        cursor = await self.conn.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return {str(row["name"]) for row in rows}

    async def _migrate(self) -> None:
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        cursor = await self.conn.execute("SELECT MAX(version) FROM schema_migrations")
        row = await cursor.fetchone()
        version = int(row[0] or 0) if row else 0
        if version >= SCHEMA_VERSION:
            return

        is_legacy = False
        if await self._table_exists("users"):
            columns = await self._columns("users")
            is_legacy = "roadmap_progress" not in columns

        if is_legacy:
            await self._migrate_v1()
        else:
            await self.conn.executescript(SCHEMA)

        await self.conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, _now()),
        )
        await self.conn.commit()

    async def _migrate_v1(self) -> None:
        """Copy the original two-table schema into v2, keeping a backup."""
        logger.info("Migrating v1 database to schema v%s", SCHEMA_VERSION)
        await self.conn.execute("ALTER TABLE users RENAME TO users_v1_backup")
        await self.conn.execute("ALTER TABLE cohorts RENAME TO cohorts_v1_backup")
        await self.conn.executescript(SCHEMA)
        now = _now()
        await self.conn.execute(
            """
            INSERT INTO cohorts (cohort_id, name, guild_id, channel_id, host_id, created_at)
            SELECT cohort_id, name, NULL, NULL, NULL, ? FROM cohorts_v1_backup
            """,
            (now,),
        )
        await self.conn.execute(
            """
            INSERT INTO users (
                user_id, discord_username, lc_username, cohort_id, roadmap,
                goal_questions, goal_duration, goal_start_date, goal_baseline,
                reminder_hour, reminder_minute, timezone, created_at, updated_at
            )
            SELECT
                NULL, discord_username, lc_username,
                CASE
                    WHEN cohort_id IN (SELECT cohort_id FROM cohorts) THEN cohort_id
                    ELSE NULL
                END,
                roadmap, goal_questions, goal_duration, goal_start_date, NULL,
                reminder_hour, reminder_minute, 'UTC', ?, ?
            FROM users_v1_backup
            WHERE lc_username IS NOT NULL AND TRIM(lc_username) != ''
            """,
            (now, now),
        )
        logger.info("Legacy rows copied; originals kept as *_v1_backup")

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    async def get_user(self, user_id: int) -> UserRecord | None:
        cursor = await self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        return UserRecord.from_row(row) if row else None

    async def get_user_by_lc_username(self, lc_username: str) -> UserRecord | None:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE lc_username = ? COLLATE NOCASE LIMIT 1", (lc_username,)
        )
        row = await cursor.fetchone()
        return UserRecord.from_row(row) if row else None

    async def link_user(
        self,
        user_id: int,
        discord_username: str,
        lc_username: str,
        *,
        timezone: str = "UTC",
    ) -> UserRecord:
        """Create, update or claim a linked account."""
        async with self._write_lock:
            existing = await self.get_user(user_id)
            conflict = await self.conn.execute(
                """
                SELECT 1 FROM users
                WHERE lc_username = ? COLLATE NOCASE AND user_id IS NOT NULL AND user_id != ?
                LIMIT 1
                """,
                (lc_username, user_id),
            )
            if await conflict.fetchone():
                raise UsernameTakenError(
                    "That LeetCode username is already linked to another Discord account."
                )

            now = _now()
            if existing is not None:
                await self.conn.execute(
                    """
                    UPDATE users
                    SET discord_username=?, lc_username=?, updated_at=?
                    WHERE user_id=?
                    """,
                    (discord_username, lc_username, now, user_id),
                )
            else:
                legacy = await self._find_legacy_row(discord_username, lc_username)
                if legacy is not None:
                    await self.conn.execute(
                        """
                        UPDATE users
                        SET user_id=?, discord_username=?, lc_username=?, updated_at=?
                        WHERE id=?
                        """,
                        (user_id, discord_username, lc_username, now, legacy["id"]),
                    )
                    logger.info("Claimed legacy row %s for user %s", legacy["id"], user_id)
                else:
                    await self.conn.execute(
                        """
                        INSERT INTO users (
                            user_id, discord_username, lc_username, timezone,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, discord_username, lc_username, timezone, now, now),
                    )
            await self.conn.commit()
        user = await self.get_user(user_id)
        if user is None:  # pragma: no cover - defensive
            raise RuntimeError("Failed to persist user")
        return user

    async def _find_legacy_row(
        self, discord_username: str, lc_username: str
    ) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            """
            SELECT * FROM users
            WHERE user_id IS NULL
              AND (
                discord_username = ?
                OR discord_username LIKE ? || '#%'
                OR lc_username = ? COLLATE NOCASE
              )
            LIMIT 1
            """,
            (discord_username, discord_username, lc_username),
        )
        return await cursor.fetchone()

    async def unlink_user(self, user_id: int) -> None:
        """Remove a linked account."""
        async with self._write_lock:
            await self.conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
            await self.conn.execute("UPDATE cohorts SET host_id=NULL WHERE host_id=?", (user_id,))
            await self.conn.commit()

    async def set_roadmap(
        self, user_id: int, roadmap: str, progress: list[str] | tuple[str, ...] = ()
    ) -> None:
        await self._update(
            user_id, "roadmap=?, roadmap_progress=?", (roadmap, json.dumps(list(progress)))
        )

    async def set_roadmap_progress(
        self, user_id: int, progress: list[str] | tuple[str, ...]
    ) -> None:
        await self._update(user_id, "roadmap_progress=?", (json.dumps(list(progress)),))

    async def set_goal(
        self,
        user_id: int,
        questions: int,
        months: int,
        start_date: date,
        baseline: int,
    ) -> None:
        await self._update(
            user_id,
            "goal_questions=?, goal_duration=?, goal_start_date=?, goal_baseline=?",
            (questions, months, start_date.isoformat(), baseline),
        )

    async def clear_goal(self, user_id: int) -> None:
        await self._update(
            user_id,
            "goal_questions=NULL, goal_duration=NULL, goal_start_date=NULL, goal_baseline=NULL",
            (),
        )

    async def set_reminder(self, user_id: int, hour: int, minute: int, timezone: str) -> None:
        await self._update(
            user_id,
            "reminder_hour=?, reminder_minute=?, timezone=?",
            (hour, minute, timezone),
        )

    async def clear_reminder(self, user_id: int) -> None:
        await self._update(user_id, "reminder_hour=NULL, reminder_minute=NULL", ())

    async def set_timezone(self, user_id: int, timezone: str) -> None:
        await self._update(user_id, "timezone=?", (timezone,))

    async def _update(self, user_id: int, assignments: str, values: tuple[Any, ...]) -> None:
        await self.conn.execute(
            f"UPDATE users SET {assignments}, updated_at=? WHERE user_id=?",
            (*values, _now(), user_id),
        )
        await self.conn.commit()

    async def list_linked_users(self, limit: int = 500) -> list[UserRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id IS NOT NULL ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [UserRecord.from_row(row) for row in await cursor.fetchall()]

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    async def list_reminder_users(self) -> list[UserRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE reminder_hour IS NOT NULL AND reminder_minute IS NOT NULL"
        )
        return [UserRecord.from_row(row) for row in await cursor.fetchall()]

    async def was_reminder_sent(self, user_id: int, sent_on: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM reminder_log WHERE user_id=? AND sent_on=?", (user_id, sent_on)
        )
        return await cursor.fetchone() is not None

    async def mark_reminder_sent(self, user_id: int, sent_on: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO reminder_log (user_id, sent_on, sent_at) VALUES (?, ?, ?)",
            (user_id, sent_on, _now()),
        )
        await self.conn.commit()

    async def cleanup_reminder_log(self, days: int = 30) -> int:
        cutoff = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
        cursor = await self.conn.execute("DELETE FROM reminder_log WHERE sent_on < ?", (cutoff,))
        await self.conn.commit()
        return cursor.rowcount or 0

    # ------------------------------------------------------------------
    # Cohorts
    # ------------------------------------------------------------------
    async def create_cohort(
        self,
        name: str,
        guild_id: int,
        channel_id: int,
        host_id: int,
    ) -> Cohort:
        async with self._write_lock:
            cursor = await self.conn.execute(
                "INSERT INTO cohorts (name, guild_id, channel_id, host_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, guild_id, channel_id, host_id, _now()),
            )
            cohort_id = int(cursor.lastrowid or 0)
            await self.conn.execute(
                "UPDATE users SET cohort_id=?, updated_at=? WHERE user_id=?",
                (cohort_id, _now(), host_id),
            )
            await self.conn.commit()
        cohort = await self.get_cohort(cohort_id)
        if cohort is None:  # pragma: no cover - defensive
            raise RuntimeError("Failed to create cohort")
        return cohort

    async def get_cohort(self, cohort_id: int) -> Cohort | None:
        cursor = await self.conn.execute("SELECT * FROM cohorts WHERE cohort_id=?", (cohort_id,))
        row = await cursor.fetchone()
        return Cohort.from_row(row) if row else None

    async def get_cohort_by_name(self, guild_id: int, name: str) -> Cohort | None:
        cursor = await self.conn.execute(
            "SELECT * FROM cohorts WHERE guild_id=? AND name = ? COLLATE NOCASE LIMIT 1",
            (guild_id, name),
        )
        row = await cursor.fetchone()
        return Cohort.from_row(row) if row else None

    async def get_cohort_by_channel(self, channel_id: int) -> Cohort | None:
        cursor = await self.conn.execute("SELECT * FROM cohorts WHERE channel_id=?", (channel_id,))
        row = await cursor.fetchone()
        return Cohort.from_row(row) if row else None

    async def list_cohorts(self, guild_id: int | None = None) -> list[Cohort]:
        if guild_id is None:
            cursor = await self.conn.execute("SELECT * FROM cohorts ORDER BY name")
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM cohorts WHERE guild_id=? ORDER BY name", (guild_id,)
            )
        return [Cohort.from_row(row) for row in await cursor.fetchall()]

    async def list_hosted_cohorts(self, user_id: int) -> list[Cohort]:
        cursor = await self.conn.execute(
            "SELECT * FROM cohorts WHERE host_id=? ORDER BY name", (user_id,)
        )
        return [Cohort.from_row(row) for row in await cursor.fetchall()]

    async def set_cohort_channel(self, cohort_id: int, channel_id: int) -> None:
        await self.conn.execute(
            "UPDATE cohorts SET channel_id=? WHERE cohort_id=?", (channel_id, cohort_id)
        )
        await self.conn.commit()

    async def set_cohort_host(self, cohort_id: int, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE cohorts SET host_id=? WHERE cohort_id=?", (user_id, cohort_id)
        )
        await self.conn.commit()

    async def delete_cohort(self, cohort_id: int) -> None:
        async with self._write_lock:
            await self.conn.execute(
                "UPDATE users SET cohort_id=NULL, updated_at=? WHERE cohort_id=?",
                (_now(), cohort_id),
            )
            await self.conn.execute("DELETE FROM cohorts WHERE cohort_id=?", (cohort_id,))
            await self.conn.commit()

    async def set_user_cohort(self, user_id: int, cohort_id: int) -> None:
        await self._update(user_id, "cohort_id=?", (cohort_id,))

    async def clear_user_cohort(self, user_id: int) -> None:
        await self._update(user_id, "cohort_id=NULL", ())

    async def list_cohort_members(self, cohort_id: int) -> list[UserRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE cohort_id=? AND user_id IS NOT NULL ORDER BY updated_at",
            (cohort_id,),
        )
        return [UserRecord.from_row(row) for row in await cursor.fetchall()]

    async def count_cohort_members(self, cohort_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE cohort_id=? AND user_id IS NOT NULL", (cohort_id,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    async def count_users(self) -> int:
        cursor = await self.conn.execute("SELECT COUNT(*) FROM users WHERE user_id IS NOT NULL")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def count_cohorts(self) -> int:
        cursor = await self.conn.execute("SELECT COUNT(*) FROM cohorts")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def count_active_reminders(self) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE reminder_hour IS NOT NULL"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
