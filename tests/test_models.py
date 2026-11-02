"""Goal pace calculation tests."""

from __future__ import annotations

from datetime import date

import pytest

from leetgo.models import UserRecord, calculate_goal_progress


def test_goal_starting() -> None:
    progress = calculate_goal_progress(
        target=100,
        months=1,
        start_date=date(2026, 1, 1),
        baseline=50,
        current_solved=50,
        today=date(2026, 1, 1),
    )
    assert progress.status == "starting"
    assert progress.solved == 0
    assert progress.days_total == 30
    assert progress.days_remaining == 30


def test_goal_on_track() -> None:
    progress = calculate_goal_progress(
        target=100,
        months=1,
        start_date=date(2026, 1, 1),
        baseline=100,
        current_solved=160,
        today=date(2026, 1, 16),
    )
    assert progress.status == "on_track"
    assert progress.solved == 60
    assert progress.percent == 60
    assert progress.expected == pytest.approx(50)


def test_goal_behind() -> None:
    progress = calculate_goal_progress(
        target=100,
        months=1,
        start_date=date(2026, 1, 1),
        baseline=100,
        current_solved=120,
        today=date(2026, 1, 16),
    )
    assert progress.status == "behind"
    assert progress.delta < 0


def test_goal_complete() -> None:
    progress = calculate_goal_progress(
        target=100,
        months=1,
        start_date=date(2026, 1, 1),
        baseline=100,
        current_solved=250,
        today=date(2026, 1, 10),
    )
    assert progress.status == "complete"
    assert progress.percent == 100


def test_goal_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        calculate_goal_progress(0, 1, date(2026, 1, 1), 0, 10)
    with pytest.raises(ValueError):
        calculate_goal_progress(10, 0, date(2026, 1, 1), 0, 10)


def test_user_record_helpers() -> None:
    row = {
        "id": 1,
        "user_id": 42,
        "discord_username": "alice",
        "lc_username": "alice_lc",
        "cohort_id": None,
        "roadmap": "Beginner",
        "roadmap_progress": '["Arrays & Hashing"]',
        "goal_questions": 100,
        "goal_duration": 3,
        "goal_start_date": "2026-01-01",
        "goal_baseline": 10,
        "reminder_hour": 20,
        "reminder_minute": 0,
        "timezone": "UTC",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    user = UserRecord.from_row(row)
    assert user.has_goal is True
    assert user.has_reminder is True
    assert user.roadmap_progress == ("Arrays & Hashing",)
