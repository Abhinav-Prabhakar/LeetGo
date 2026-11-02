"""Timezone and reminder scheduling tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from leetgo.timezones import (
    is_due,
    local_now,
    next_occurrence,
    search_timezones,
    validate_timezone,
)


def test_validate_timezone() -> None:
    assert validate_timezone("UTC") == "UTC"
    with pytest.raises(ValueError):
        validate_timezone("Mars/Olympus_Mons")


def test_local_now() -> None:
    reference = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    local = local_now("Asia/Kolkata", reference)
    assert local.hour == 17
    assert local.minute == 30
    assert local.tzinfo is not None


def test_next_occurrence_same_day() -> None:
    reference = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    result = next_occurrence(20, 0, "UTC", reference)
    assert result == datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


def test_next_occurrence_tomorrow() -> None:
    reference = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
    result = next_occurrence(20, 0, "UTC", reference)
    assert result == datetime(2026, 1, 2, 20, 0, tzinfo=UTC)


def test_next_occurrence_across_timezone() -> None:
    reference = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    # 20:00 IST is 14:30 UTC.
    result = next_occurrence(20, 0, "Asia/Kolkata", reference)
    assert result == datetime(2026, 1, 1, 14, 30, tzinfo=UTC)


def test_is_due_window() -> None:
    due, key = is_due(20, 0, "UTC", datetime(2026, 1, 1, 20, 0, 30, tzinfo=UTC))
    assert due is True
    assert key == "2026-01-01"
    due, _ = is_due(20, 0, "UTC", datetime(2026, 1, 1, 20, 2, 59, tzinfo=UTC))
    assert due is True
    due, _ = is_due(20, 0, "UTC", datetime(2026, 1, 1, 20, 3, 1, tzinfo=UTC))
    assert due is False
    due, _ = is_due(20, 0, "UTC", datetime(2026, 1, 1, 19, 59, 59, tzinfo=UTC))
    assert due is False


def test_search_timezones() -> None:
    assert "Asia/Kolkata" in search_timezones("kolkata")
    assert search_timezones("")[0] == "UTC"
    assert len(search_timezones("America")) <= 25
