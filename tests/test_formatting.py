"""Tests for pure formatting helpers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from leetgo.formatting import (
    clamp,
    discord_timestamp,
    format_number,
    format_percent,
    format_solved,
    humanize_duration,
    parse_date,
    parse_datetime,
    pluralize,
    progress_bar,
    sanitize_channel_name,
    truncate,
)


def test_progress_bar_edges() -> None:
    assert progress_bar(0) == "▱" * 10
    assert progress_bar(100) == "▰" * 10
    assert progress_bar(50) == "▰" * 5 + "▱" * 5
    assert progress_bar(150) == "▰" * 10
    assert progress_bar(-10) == "▱" * 10


def test_progress_bar_custom_length() -> None:
    assert len(progress_bar(40, 5)) == 5
    with pytest.raises(ValueError):
        progress_bar(50, 0)


def test_number_and_percent_formatting() -> None:
    assert format_number(1234567) == "1,234,567"
    assert format_percent(42.135) == "42.1%"
    assert format_percent(120) == "100.0%"
    assert format_solved(50, 100) == "**50** / 100 (50.0%)"
    assert format_solved(50, 0) == "50 solved"


def test_clamp() -> None:
    assert clamp(5) == 5
    assert clamp(-1) == 0
    assert clamp(101) == 100


def test_sanitize_channel_name() -> None:
    assert sanitize_channel_name("Hello, World!") == "hello-world"
    assert sanitize_channel_name("  Multiple   Spaces  ") == "multiple-spaces"
    assert sanitize_channel_name("---") == "cohort"
    assert len(sanitize_channel_name("a" * 200)) == 90
    assert sanitize_channel_name("Café Study") == "cafe-study"


def test_truncate() -> None:
    assert truncate("abcdef", 4) == "abc…"
    assert truncate("abc", 10) == "abc"
    assert truncate("abcdef", 1) == "…"
    with pytest.raises(ValueError):
        truncate("abc", 0)


def test_pluralize_and_duration() -> None:
    assert pluralize(1, "day") == "1 day"
    assert pluralize(2, "day") == "2 days"
    assert pluralize(2, "entry", "entries") == "2 entries"
    assert humanize_duration(timedelta(days=3, hours=4)) == "3d 4h"
    assert humanize_duration(timedelta(hours=2, minutes=5)) == "2h 5m"
    assert humanize_duration(timedelta(minutes=1, seconds=2)) == "1m 2s"
    assert humanize_duration(timedelta(seconds=9)) == "9s"


def test_date_parsing() -> None:
    assert parse_date("2026-01-02").isoformat() == "2026-01-02"  # type: ignore[union-attr]
    assert parse_date("not-a-date") is None
    assert parse_date(None) is None
    parsed = parse_datetime("2026-01-02T03:04:05+00:00")
    assert parsed is not None and parsed.year == 2026
    assert parse_datetime("") is None


def test_discord_timestamp() -> None:
    assert discord_timestamp(0) == "<t:0:R>"
