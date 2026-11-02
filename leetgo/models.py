"""Domain records shared by the database and cogs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

GoalStatus = Literal["complete", "on_track", "behind", "starting"]


@dataclass(slots=True, frozen=True)
class UserRecord:
    """A linked Discord/LeetCode account."""

    id: int
    user_id: int | None
    discord_username: str | None
    lc_username: str
    cohort_id: int | None
    roadmap: str | None
    roadmap_progress: tuple[str, ...]
    goal_questions: int | None
    goal_duration: int | None
    goal_start_date: str | None
    goal_baseline: int | None
    reminder_hour: int | None
    reminder_minute: int | None
    timezone: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> UserRecord:
        """Build a record from a sqlite row."""
        raw_progress = row["roadmap_progress"] or "[]"
        try:
            parsed = json.loads(raw_progress)
            progress = tuple(str(item) for item in parsed) if isinstance(parsed, list) else ()
        except (TypeError, ValueError):
            progress = ()
        return cls(
            id=int(row["id"]),
            user_id=row["user_id"],
            discord_username=row["discord_username"],
            lc_username=row["lc_username"],
            cohort_id=row["cohort_id"],
            roadmap=row["roadmap"],
            roadmap_progress=progress,
            goal_questions=row["goal_questions"],
            goal_duration=row["goal_duration"],
            goal_start_date=row["goal_start_date"],
            goal_baseline=row["goal_baseline"],
            reminder_hour=row["reminder_hour"],
            reminder_minute=row["reminder_minute"],
            timezone=row["timezone"] or "UTC",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @property
    def has_goal(self) -> bool:
        """Whether a goal is configured."""
        return bool(self.goal_questions and self.goal_duration and self.goal_start_date)

    @property
    def has_reminder(self) -> bool:
        """Whether a reminder is configured."""
        return self.reminder_hour is not None and self.reminder_minute is not None


@dataclass(slots=True, frozen=True)
class Cohort:
    """A study cohort bound to a Discord channel."""

    cohort_id: int
    name: str
    guild_id: int | None
    channel_id: int | None
    host_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> Cohort:
        """Build a cohort from a sqlite row."""
        return cls(
            cohort_id=int(row["cohort_id"]),
            name=str(row["name"]),
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            host_id=row["host_id"],
            created_at=row["created_at"],
        )


@dataclass(slots=True, frozen=True)
class GoalProgress:
    """Computed progress for a personal solving goal."""

    solved: int
    target: int
    baseline: int
    percent: float
    days_elapsed: int
    days_total: int
    days_remaining: int
    expected: float
    delta: float
    status: GoalStatus
    start_date: date
    end_date: date

    @property
    def status_label(self) -> str:
        """Human-friendly status label."""
        return {
            "complete": "Goal complete 🎉",
            "on_track": "On track ✅",
            "behind": "Behind pace ⚠️",
            "starting": "Just getting started 🌱",
        }[self.status]


def calculate_goal_progress(
    target: int,
    months: int,
    start_date: date,
    baseline: int,
    current_solved: int,
    today: date | None = None,
) -> GoalProgress:
    """Calculate goal progress and pace against a linear target."""
    today = today or datetime.now(UTC).date()
    if target <= 0:
        raise ValueError("target must be positive")
    if months <= 0:
        raise ValueError("months must be positive")

    total_days = max(1, round(months * 30.4375))
    end_date = start_date + timedelta(days=total_days)
    elapsed = min(max((today - start_date).days, 0), total_days)
    remaining = max(0, (end_date - today).days)
    solved = max(0, current_solved - baseline)
    percent = min(100.0, solved / target * 100)
    expected = target * (elapsed / total_days)
    delta = solved - expected

    if solved >= target:
        status: GoalStatus = "complete"
    elif elapsed == 0 and solved == 0:
        status = "starting"
    elif delta >= -max(1.0, target * 0.05):
        status = "on_track"
    else:
        status = "behind"

    return GoalProgress(
        solved=solved,
        target=target,
        baseline=baseline,
        percent=percent,
        days_elapsed=elapsed,
        days_total=total_days,
        days_remaining=remaining,
        expected=expected,
        delta=delta,
        status=status,
        start_date=start_date,
        end_date=end_date,
    )


@dataclass(slots=True)
class LeaderboardEntry:
    """A single row on a leaderboard."""

    user_id: int
    lc_username: str
    total_solved: int
    easy: int = 0
    medium: int = 0
    hard: int = 0
    ranking: int | None = None
    contest_rating: float | None = None
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
