"""Shared pytest fixtures and factories."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from leetgo.db import Database
from leetgo.models import UserRecord


@pytest_asyncio.fixture
async def db(tmp_path: Any) -> Database:
    """A connected, isolated SQLite database."""
    database = Database(tmp_path / "leetgo.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def make_user() -> Any:
    """Factory for UserRecord instances used by service tests."""

    def factory(
        user_id: int = 1,
        lc_username: str = "alice",
        *,
        cohort_id: int | None = None,
    ) -> UserRecord:
        return UserRecord(
            id=user_id,
            user_id=user_id,
            discord_username=f"user{user_id}",
            lc_username=lc_username,
            cohort_id=cohort_id,
            roadmap=None,
            roadmap_progress=(),
            goal_questions=None,
            goal_duration=None,
            goal_start_date=None,
            goal_baseline=None,
            reminder_hour=None,
            reminder_minute=None,
            timezone="UTC",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    return factory
