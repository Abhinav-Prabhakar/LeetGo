"""Database persistence, migration and cascade tests."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from leetgo.db import Database
from leetgo.errors import UsernameTakenError


async def test_link_user_and_update(db: Database) -> None:
    user = await db.link_user(1, "alice", "alice_lc")
    assert user.user_id == 1
    assert user.lc_username == "alice_lc"
    assert user.timezone == "UTC"
    assert await db.count_users() == 1

    updated = await db.link_user(1, "alice-renamed", "alice_new")
    assert updated.lc_username == "alice_new"
    assert updated.discord_username == "alice-renamed"
    assert await db.count_users() == 1


async def test_duplicate_username_case_insensitive(db: Database) -> None:
    await db.link_user(1, "alice", "same_name")
    with pytest.raises(UsernameTakenError):
        await db.link_user(2, "bob", "SAME_NAME")
    with pytest.raises(UsernameTakenError):
        await db.link_user(2, "bob", "same_name")


async def test_roadmap_goal_and_reminder(db: Database) -> None:
    await db.link_user(1, "alice", "alice_lc")
    await db.set_roadmap(1, "Beginner", ["Arrays & Hashing"])
    user = await db.get_user(1)
    assert user is not None
    assert user.roadmap == "Beginner"
    assert user.roadmap_progress == ("Arrays & Hashing",)

    await db.set_roadmap_progress(1, ["Arrays & Hashing", "Two Pointers"])
    user = await db.get_user(1)
    assert user is not None
    assert len(user.roadmap_progress) == 2

    await db.set_goal(1, 100, 3, start_date=date(2026, 1, 1), baseline=20)
    user = await db.get_user(1)
    assert user is not None and user.has_goal
    assert user.goal_baseline == 20
    await db.clear_goal(1)
    user = await db.get_user(1)
    assert user is not None and not user.has_goal

    await db.set_reminder(1, 20, 30, "Asia/Kolkata")
    user = await db.get_user(1)
    assert user is not None and user.has_reminder
    assert user.timezone == "Asia/Kolkata"
    assert user.reminder_hour == 20

    reminder_users = await db.list_reminder_users()
    assert len(reminder_users) == 1
    assert await db.count_active_reminders() == 1

    await db.mark_reminder_sent(1, "2026-01-01")
    assert await db.was_reminder_sent(1, "2026-01-01") is True
    assert await db.was_reminder_sent(1, "2026-01-02") is False

    await db.clear_reminder(1)
    user = await db.get_user(1)
    assert user is not None and not user.has_reminder


async def test_cohort_lifecycle(db: Database) -> None:
    await db.link_user(1, "host", "host_lc")
    await db.link_user(2, "guest", "guest_lc")
    cohort = await db.create_cohort("Study Group", 10, 100, 1)
    assert cohort.name == "Study Group"
    assert cohort.channel_id == 100

    host = await db.get_user(1)
    assert host is not None and host.cohort_id == cohort.cohort_id
    by_name = await db.get_cohort_by_name(10, "study group")
    assert by_name is not None and by_name.cohort_id == cohort.cohort_id
    by_channel = await db.get_cohort_by_channel(100)
    assert by_channel is not None and by_channel.cohort_id == cohort.cohort_id
    assert len(await db.list_hosted_cohorts(1)) == 1

    await db.set_user_cohort(2, cohort.cohort_id)
    members = await db.list_cohort_members(cohort.cohort_id)
    assert len(members) == 2
    assert await db.count_cohort_members(cohort.cohort_id) == 2

    await db.clear_user_cohort(2)
    assert await db.count_cohort_members(cohort.cohort_id) == 1

    await db.delete_cohort(cohort.cohort_id)
    assert await db.get_cohort(cohort.cohort_id) is None
    host = await db.get_user(1)
    assert host is not None and host.cohort_id is None
    assert await db.count_cohorts() == 0


async def test_unlink_cascades(db: Database) -> None:
    await db.link_user(1, "alice", "alice_lc")
    await db.set_reminder(1, 8, 0, "UTC")
    await db.mark_reminder_sent(1, "2026-01-01")
    await db.unlink_user(1)
    assert await db.get_user(1) is None
    assert await db.was_reminder_sent(1, "2026-01-01") is False


async def test_metrics(db: Database) -> None:
    assert await db.health_check() is True
    assert await db.count_users() == 0
    await db.link_user(1, "alice", "alice_lc")
    await db.link_user(2, "bob", "bob_lc")
    await db.set_reminder(1, 8, 0, "UTC")
    await db.create_cohort("Test", 1, 2, 1)
    assert await db.count_users() == 2
    assert await db.count_cohorts() == 1
    assert await db.count_active_reminders() == 1


def _create_v1_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cohorts (
            cohort_id INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY NOT NULL,
            cohort_id INTEGER,
            discord_username TEXT NOT NULL UNIQUE,
            lc_username TEXT,
            roadmap TEXT,
            goal_questions INTEGER,
            goal_duration INTEGER,
            goal_start_date TEXT,
            reminder_hour INTEGER,
            reminder_minute INTEGER,
            FOREIGN KEY(cohort_id) REFERENCES cohorts(cohort_id)
        );
        INSERT INTO cohorts (cohort_id, name) VALUES (1, 'Legacy Cohort');
        INSERT INTO users (
            cohort_id, discord_username, lc_username, roadmap,
            goal_questions, goal_duration, goal_start_date,
            reminder_hour, reminder_minute
        ) VALUES (1, 'legacy#1234', 'legacy_lc', 'Beginner', 120, 3, '2025-01-01', 20, 0);
        """
    )
    connection.commit()
    connection.close()


async def test_migrates_v1_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _create_v1_database(path)
    database = Database(path)
    await database.connect()
    try:
        cursor = await database.conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        assert row is not None and row[0] == 2

        cursor = await database.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('users_v1_backup', 'cohorts_v1_backup')"
        )
        backups = {row[0] for row in await cursor.fetchall()}
        assert backups == {"users_v1_backup", "cohorts_v1_backup"}

        legacy = await database.get_user_by_lc_username("legacy_lc")
        assert legacy is not None
        assert legacy.user_id is None
        assert legacy.cohort_id == 1
        assert legacy.roadmap == "Beginner"
        assert legacy.goal_questions == 120
        assert legacy.reminder_hour == 20

        cohorts = await database.list_cohorts()
        assert len(cohorts) == 1
        assert cohorts[0].name == "Legacy Cohort"

        claimed = await database.link_user(42, "legacy", "legacy_lc")
        assert claimed.user_id == 42
        assert claimed.discord_username == "legacy"
        assert claimed.goal_questions == 120
        assert claimed.roadmap == "Beginner"
        assert claimed.cohort_id == 1
    finally:
        await database.close()


async def test_auto_imports_legacy_storage_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _create_v1_database(tmp_path / "storage.db")
    database = Database(tmp_path / "data" / "leetgo.db")
    await database.connect()
    try:
        assert (tmp_path / "data" / "leetgo.db").exists()
        legacy = await database.get_user_by_lc_username("legacy_lc")
        assert legacy is not None
        assert legacy.goal_questions == 120
    finally:
        await database.close()


async def test_claims_legacy_row_by_lc_username(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _create_v1_database(path)
    database = Database(path)
    await database.connect()
    try:
        claimed = await database.link_user(42, "renamed_discord_user", "LEGACY_LC")
        assert claimed.user_id == 42
        assert claimed.discord_username == "renamed_discord_user"
        assert claimed.lc_username == "LEGACY_LC"
        assert claimed.goal_questions == 120
        assert claimed.cohort_id == 1
    finally:
        await database.close()


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _create_v1_database(path)
    for _ in range(2):
        database = Database(path)
        await database.connect()
        assert await database.get_user_by_lc_username("legacy_lc") is not None
        await database.close()
