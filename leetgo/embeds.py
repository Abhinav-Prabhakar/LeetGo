"""Reusable Discord embed builders."""

from __future__ import annotations

from datetime import UTC, date, datetime

import discord

from .constants import (
    BRAND_COLOR,
    DIFFICULTY_COLORS,
    DIFFICULTY_EMOJI,
    ERROR_COLOR,
    FOOTER_TEXT,
    INFO_COLOR,
    MUTED_COLOR,
    ROADMAPS,
    SUCCESS_COLOR,
    WARNING_COLOR,
)
from .formatting import (
    discord_timestamp,
    format_number,
    format_percent,
    format_solved,
    parse_date,
    progress_bar,
    truncate,
)
from .leetcode import DailyChallenge, UserProfile
from .models import Cohort, GoalProgress, LeaderboardEntry, UserRecord, calculate_goal_progress


def _end_timestamp(value: date, style: str = "d") -> str:
    return discord_timestamp(datetime.combine(value, datetime.min.time(), tzinfo=UTC), style)


def base_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: int = BRAND_COLOR,
    url: str | None = None,
) -> discord.Embed:
    """Create a branded embed with footer and timestamp."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        url=url,
        timestamp=datetime.now(UTC),
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def success_embed(title: str, description: str | None = None) -> discord.Embed:
    """Green success embed."""
    return base_embed(title=title, description=description, color=SUCCESS_COLOR)


def error_embed(title: str, description: str | None = None) -> discord.Embed:
    """Red error embed."""
    return base_embed(title=title, description=description, color=ERROR_COLOR)


def warning_embed(title: str, description: str | None = None) -> discord.Embed:
    """Amber warning embed."""
    return base_embed(title=title, description=description, color=WARNING_COLOR)


def info_embed(title: str, description: str | None = None) -> discord.Embed:
    """Blurple informational embed."""
    return base_embed(title=title, description=description, color=INFO_COLOR)


def muted_embed(title: str, description: str | None = None) -> discord.Embed:
    """Low-contrast neutral embed."""
    return base_embed(title=title, description=description, color=MUTED_COLOR)


def _roadmap_field(embed: discord.Embed, user: UserRecord) -> None:
    if not user.roadmap:
        return
    roadmap = ROADMAPS.get(user.roadmap)
    if roadmap is None:
        return
    done = len([topic for topic in user.roadmap_progress if topic in roadmap.topics])
    total = len(roadmap.topics)
    percent = done / total * 100 if total else 0
    embed.add_field(
        name="🗺️ Roadmap",
        value=(f"{roadmap.emoji} **{roadmap.key}**\n{progress_bar(percent)} {done}/{total} topics"),
        inline=False,
    )


def _goal_field(embed: discord.Embed, user: UserRecord, current_solved: int) -> None:
    start = parse_date(user.goal_start_date)
    if not (user.goal_questions and user.goal_duration and start):
        return
    progress = calculate_goal_progress(
        target=user.goal_questions,
        months=user.goal_duration,
        start_date=start,
        baseline=user.goal_baseline or 0,
        current_solved=current_solved,
    )
    embed.add_field(
        name="🎯 Goal",
        value=(
            f"{progress_bar(progress.percent)} **{format_percent(progress.percent)}**\n"
            f"{progress.solved}/{progress.target} solved • {progress.status_label}\n"
            f"Ends {_end_timestamp(progress.end_date)}"
        ),
        inline=False,
    )


def stats_embed(
    profile: UserProfile,
    user: UserRecord,
    *,
    display_name: str | None = None,
) -> discord.Embed:
    """Build the main LeetCode statistics card."""
    subtitle_parts = [
        part for part in (profile.real_name, profile.country, profile.company) if part
    ]
    embed = base_embed(
        title=f"📊 {display_name or profile.username}",
        description=" • ".join(subtitle_parts) or None,
        url=profile.profile_url,
    )
    if profile.avatar_url:
        embed.set_thumbnail(url=profile.avatar_url)

    embed.add_field(
        name="Overall",
        value=(
            f"{format_solved(profile.total_solved, profile.total_questions)}\n"
            f"{progress_bar(profile.overall_percent)}"
        ),
        inline=False,
    )
    for level in ("Easy", "Medium", "Hard"):
        stat = profile.difficulty.get(level)
        if stat is None:
            continue
        embed.add_field(
            name=f"{DIFFICULTY_EMOJI[level]} {level}",
            value=f"{format_solved(stat.solved, stat.total)}\n{progress_bar(stat.percent)}",
            inline=True,
        )

    stats_lines = [
        f"🔥 **Streak** {format_number(profile.streak)} days",
        f"📅 **Active** {format_number(profile.total_active_days)} days",
        f"🏆 **Rank** {'#' + format_number(profile.ranking) if profile.ranking else '—'}",
        f"🌟 **Reputation** {format_number(profile.reputation)}",
    ]
    embed.add_field(name="Activity", value="\n".join(stats_lines), inline=False)

    if profile.contest is not None and profile.contest.attended > 0:
        contest = profile.contest
        top = f" • top {format_percent(contest.top_percentage)}" if contest.top_percentage else ""
        embed.add_field(
            name="⚔️ Contest",
            value=(
                f"**{format_number(round(contest.rating))}** rating\n"
                f"{contest.attended} contests{top}"
            ),
            inline=True,
        )

    if profile.badges:
        embed.add_field(
            name="🏅 Badges",
            value=truncate(" · ".join(profile.badges[:5]), 200),
            inline=True,
        )

    if profile.recent:
        lines = [
            f"• [{truncate(item.title, 48)}]({item.url}) {discord_timestamp(item.timestamp)}"
            for item in profile.recent[:3]
        ]
        embed.add_field(name="🕒 Recent solves", value="\n".join(lines), inline=False)

    _roadmap_field(embed, user)
    _goal_field(embed, user, profile.total_solved)
    return embed


def profile_embed(
    user: UserRecord,
    *,
    display_name: str,
    avatar_url: str | None = None,
    profile: UserProfile | None = None,
) -> discord.Embed:
    """Build the account/profile card (works without a live API response)."""
    embed = base_embed(
        title=f"👤 {display_name}",
        description=f"LeetCode: **[{user.lc_username}](https://leetcode.com/u/{user.lc_username}/)**",
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    if profile is not None:
        embed.add_field(
            name="📈 Solved",
            value=(
                f"**{format_number(profile.total_solved)}** / "
                f"{format_number(profile.total_questions)}"
            ),
            inline=True,
        )
        embed.add_field(name="🔥 Streak", value=f"{profile.streak} days", inline=True)
        embed.add_field(
            name="🏆 Rank",
            value=f"#{format_number(profile.ranking)}" if profile.ranking else "—",
            inline=True,
        )
        if profile.contest and profile.contest.attended:
            embed.add_field(
                name="⚔️ Contest rating",
                value=f"{format_number(round(profile.contest.rating))} "
                f"({profile.contest.attended} contests)",
                inline=True,
            )
    else:
        embed.add_field(
            name="📈 LeetCode",
            value="Stats are temporarily unavailable.",
            inline=False,
        )
    embed.add_field(
        name="🗓️ Linked",
        value=discord_timestamp(datetime.fromisoformat(user.created_at), "d"),
        inline=True,
    )
    _roadmap_field(embed, user)
    if profile is not None:
        _goal_field(embed, user, profile.total_solved)
    elif user.has_goal:
        embed.add_field(
            name="🎯 Goal",
            value=f"Solve {format_number(user.goal_questions or 0)} questions "
            f"in {user.goal_duration} months (stats unavailable)",
            inline=False,
        )
    return embed


def daily_embed(daily: DailyChallenge) -> discord.Embed:
    """Build the daily challenge card."""
    color = DIFFICULTY_COLORS.get(daily.difficulty, BRAND_COLOR)
    embed = base_embed(
        title="🧩 Daily Challenge",
        description=f"### [{daily.title}]({daily.url})\n{daily.date}",
        color=color,
    )
    embed.add_field(
        name="Difficulty",
        value=f"{DIFFICULTY_EMOJI.get(daily.difficulty, '⚪')} {daily.difficulty}",
        inline=True,
    )
    embed.add_field(name="Acceptance", value=format_percent(daily.ac_rate), inline=True)
    embed.add_field(name="Solve", value=f"[Open on LeetCode]({daily.url})", inline=True)
    return embed


def goal_embed(progress: GoalProgress, lc_username: str) -> discord.Embed:
    """Build a goal progress card."""
    color = {
        "complete": SUCCESS_COLOR,
        "on_track": SUCCESS_COLOR,
        "behind": WARNING_COLOR,
        "starting": INFO_COLOR,
    }[progress.status]
    embed = base_embed(
        title=f"🎯 {lc_username}'s Goal",
        description=(
            f"Solve **{format_number(progress.target)}** questions in "
            f"**{max(1, round(progress.days_total / 30.4375))}** months"
        ),
        color=color,
    )
    embed.add_field(
        name="Progress",
        value=(
            f"{progress_bar(progress.percent)} **{format_percent(progress.percent)}**\n"
            f"{format_number(progress.solved)} / {format_number(progress.target)} solved"
        ),
        inline=False,
    )
    embed.add_field(
        name="Pace",
        value=(
            f"{progress.status_label}\n"
            f"Expected ~{format_number(round(progress.expected))} by now\n"
            f"{'+' if progress.delta >= 0 else ''}{format_number(round(progress.delta))} vs pace"
        ),
        inline=True,
    )
    embed.add_field(
        name="Timeline",
        value=(
            f"Day {progress.days_elapsed}/{progress.days_total}\n"
            f"{progress.days_remaining} days remaining\n"
            f"Ends {_end_timestamp(progress.end_date, 'D')}"
        ),
        inline=True,
    )
    embed.set_footer(text="Update your baseline with /goal set whenever you restart.")
    return embed


def leaderboard_embed(
    entries: list[LeaderboardEntry],
    *,
    title: str,
    subtitle: str | None = None,
) -> discord.Embed:
    """Build a leaderboard card."""
    embed = base_embed(title=title, description=subtitle)
    if not entries:
        embed.add_field(name="No data yet", value="Nobody has linked a LeetCode account.")
        return embed
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines: list[str] = []
    for position, entry in enumerate(entries, start=1):
        prefix = medals.get(position, f"`#{position:02d}`")
        if entry.error:
            lines.append(f"{prefix} **{entry.lc_username}** — _unavailable_")
            continue
        detail = f"**{format_number(entry.total_solved)}** solved"
        if entry.contest_rating:
            detail += f" • {format_number(round(entry.contest_rating))} rating"
        lines.append(f"{prefix} **{entry.lc_username}** — {detail}")
    embed.add_field(name="Rankings", value="\n".join(lines), inline=False)
    return embed


def cohort_embed(
    cohort: Cohort,
    *,
    host_name: str,
    member_count: int,
    channel_mention: str | None,
) -> discord.Embed:
    """Build a cohort overview card."""
    embed = base_embed(
        title=f"📚 {cohort.name}",
        description=f"Study cohort hosted by **{host_name}**",
    )
    embed.add_field(name="Members", value=str(member_count), inline=True)
    embed.add_field(
        name="Channel",
        value=channel_mention or "Not linked",
        inline=True,
    )
    embed.add_field(
        name="Created",
        value=discord_timestamp(datetime.fromisoformat(cohort.created_at), "D"),
        inline=True,
    )
    embed.set_footer(text="Use /cohort leaderboard to see how the group is doing.")
    return embed
