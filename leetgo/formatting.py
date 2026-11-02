"""Small pure helpers shared by embeds, cogs and tests."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime, timedelta

from .constants import PROGRESS_BAR_LENGTH, PROGRESS_EMPTY, PROGRESS_FILLED


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp ``value`` to the inclusive ``low``..``high`` range."""
    return max(low, min(high, value))


def progress_bar(percent: float, length: int = PROGRESS_BAR_LENGTH) -> str:
    """Render a smooth block progress bar for a percentage."""
    if length < 1:
        raise ValueError("length must be at least 1")
    filled = round(clamp(percent) / 100 * length)
    return PROGRESS_FILLED * filled + PROGRESS_EMPTY * (length - filled)


def format_number(value: int | float) -> str:
    """Format an integer with thousands separators."""
    return f"{int(value):,}"


def format_percent(value: float, decimals: int = 1) -> str:
    """Format a percentage with a trailing percent sign."""
    return f"{clamp(value):.{decimals}f}%"


def format_solved(solved: int, total: int) -> str:
    """Render ``solved / total`` with a safe percentage."""
    if total <= 0:
        return f"{format_number(solved)} solved"
    return (
        f"**{format_number(solved)}** / {format_number(total)} "
        f"({format_percent(solved / total * 100)})"
    )


def truncate(text: str, limit: int = 100, suffix: str = "…") -> str:
    """Truncate ``text`` to at most ``limit`` characters."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def sanitize_channel_name(name: str, max_length: int = 90) -> str:
    """Convert arbitrary text into a valid Discord channel slug."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_length].strip("-") or "cohort"


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """Return the correctly pluralised noun for ``count``."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{format_number(count)} {word}"


def humanize_duration(delta: timedelta) -> str:
    """Render a compact human duration such as ``3d 4h``."""
    total_seconds = int(abs(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def parse_date(value: str | None) -> date | None:
    """Parse an ISO date, returning ``None`` for empty or invalid values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime, returning ``None`` for empty or invalid values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


def discord_timestamp(value: datetime | int, style: str = "R") -> str:
    """Render a Discord timestamp marker."""
    timestamp = int(value.timestamp()) if isinstance(value, datetime) else value
    return f"<t:{timestamp}:{style}>"


def days_between(start: date, end: date) -> int:
    """Return the whole number of days between two dates."""
    return (end - start).days
