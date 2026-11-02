"""Timezone-aware helpers for reminders and displays."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


def get_zone(name: str) -> ZoneInfo:
    """Return a ``ZoneInfo`` or raise ``ValueError`` with a friendly message."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {name!r}") from exc


def validate_timezone(name: str) -> str:
    """Validate and return an IANA timezone name."""
    get_zone(name)
    return name


def local_now(timezone: str, now: datetime | None = None) -> datetime:
    """Return the current time in ``timezone``."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference.astimezone(get_zone(timezone))


def next_occurrence(
    hour: int,
    minute: int,
    timezone: str,
    now: datetime | None = None,
) -> datetime:
    """Return the next UTC datetime matching ``hour:minute`` in ``timezone``."""
    zone = get_zone(timezone)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    local = reference.astimezone(zone)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    # Normalising through UTC keeps DST transitions correct.
    return candidate.astimezone(UTC)


def is_due(
    hour: int,
    minute: int,
    timezone: str,
    now: datetime | None = None,
    window_seconds: int = 180,
) -> tuple[bool, str]:
    """Return whether a reminder is due now, plus the user's local date key.

    A small delivery window makes the scheduler resilient to loop drift and
    short restarts. The date key guarantees at most one delivery per local day.
    """
    local = local_now(timezone, now)
    scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (local - scheduled).total_seconds()
    due = 0 <= delta < window_seconds
    return due, local.date().isoformat()


def search_timezones(query: str, limit: int = 25) -> list[str]:
    """Search IANA timezones for autocomplete suggestions."""
    query = query.strip().lower()
    zones = sorted(available_timezones())
    if not query:
        from .constants import COMMON_TIMEZONES

        return list(COMMON_TIMEZONES)[:limit]
    starts = [zone for zone in zones if zone.lower().startswith(query)]
    contains = [zone for zone in zones if query in zone.lower() and zone not in starts]
    return (starts + contains)[:limit]
