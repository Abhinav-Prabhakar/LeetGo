"""Embed rendering tests — the bot's visible product surface."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from leetgo.constants import (
    BRAND_COLOR,
    ERROR_COLOR,
    FOOTER_TEXT,
    INFO_COLOR,
    MUTED_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)
from leetgo.embeds import (
    base_embed,
    cohort_embed,
    daily_embed,
    error_embed,
    goal_embed,
    info_embed,
    leaderboard_embed,
    muted_embed,
    profile_embed,
    stats_embed,
    success_embed,
    warning_embed,
)
from leetgo.leetcode import (
    ContestStat,
    DailyChallenge,
    DifficultyStat,
    RecentSolve,
    UserProfile,
)
from leetgo.models import Cohort, LeaderboardEntry, UserRecord, calculate_goal_progress


def make_profile(**overrides: object) -> UserProfile:
    data: dict[str, object] = {
        "username": "alice",
        "real_name": "Alice Example",
        "avatar_url": "https://example.com/avatar.png",
        "country": "India",
        "company": "Example Corp",
        "school": "Example University",
        "ranking": 12345,
        "reputation": 42,
        "star_rating": 2.5,
        "total_solved": 300,
        "total_questions": 3300,
        "difficulty": {
            "Easy": DifficultyStat(120, 800),
            "Medium": DifficultyStat(140, 1800),
            "Hard": DifficultyStat(40, 700),
        },
        "streak": 12,
        "total_active_days": 100,
        "contest": ContestStat(1800.5, 10, 1234, 5.2),
        "badges": ("Guardian", "Annual Badge"),
        "recent": (
            RecentSolve("Two Sum", "two-sum", 1700000000),
            RecentSolve("Valid Parentheses", "valid-parentheses", 1700003600),
        ),
    }
    data.update(overrides)
    return UserProfile(**data)  # type: ignore[arg-type]


def make_goal_user(user: UserRecord) -> UserRecord:
    return replace(
        user,
        roadmap="Beginner",
        roadmap_progress=("Arrays & Hashing", "Two Pointers"),
        goal_questions=50,
        goal_duration=1,
        goal_start_date="2026-01-01",
        goal_baseline=100,
    )


def field_names(embed: object) -> list[str]:
    return [field.name for field in embed.fields]  # type: ignore[attr-defined]


def test_colour_helpers_and_footer() -> None:
    assert base_embed(title="Hi").color.value == BRAND_COLOR
    assert base_embed(title="Hi").footer.text == FOOTER_TEXT
    assert success_embed("ok").color.value == SUCCESS_COLOR
    assert error_embed("no").color.value == ERROR_COLOR
    assert warning_embed("wait").color.value == WARNING_COLOR
    assert info_embed("fyi").color.value == INFO_COLOR
    assert muted_embed("meh").color.value == MUTED_COLOR


def test_stats_embed_full(make_user: object) -> None:
    user = make_goal_user(make_user(1, "alice"))
    embed = stats_embed(make_profile(), user, display_name="Alice")

    assert embed.title == "📊 Alice"
    assert "Alice Example • India • Example Corp" in (embed.description or "")
    assert embed.url == "https://leetcode.com/u/alice/"
    assert embed.thumbnail.url == "https://example.com/avatar.png"
    names = field_names(embed)
    assert names[0] == "Overall"
    assert {"🟢 Easy", "🟡 Medium", "🔴 Hard", "Activity"} <= set(names)
    assert "⚔️ Contest" in names
    assert "🏅 Badges" in names
    assert "🕒 Recent solves" in names
    assert "🗺️ Roadmap" in names
    assert "🎯 Goal" in names
    goal_value = next(field.value for field in embed.fields if field.name == "🎯 Goal")
    assert "Goal complete" in goal_value
    assert "Ends" in goal_value


def test_stats_embed_minimal(make_user: object) -> None:
    user = make_user(1, "alice")
    profile = UserProfile(
        username="alice",
        real_name=None,
        avatar_url=None,
        country=None,
        company=None,
        school=None,
        ranking=None,
        reputation=0,
        star_rating=None,
        total_solved=0,
        total_questions=0,
    )
    embed = stats_embed(profile, user)
    assert embed.title == "📊 alice"
    assert embed.description is None
    assert embed.thumbnail.url is None
    assert field_names(embed) == ["Overall", "Activity"]


def test_profile_embed_with_live_stats(make_user: object) -> None:
    user = make_goal_user(make_user(1, "alice"))
    embed = profile_embed(
        user,
        display_name="Alice",
        avatar_url="https://example.com/a.png",
        profile=make_profile(),
    )
    assert embed.title == "👤 Alice"
    assert "leetcode.com/u/alice" in (embed.description or "")
    assert embed.thumbnail.url == "https://example.com/a.png"
    names = field_names(embed)
    assert {"📈 Solved", "🔥 Streak", "🏆 Rank", "⚔️ Contest rating"} <= set(names)
    assert "🗺️ Roadmap" in names
    assert "🎯 Goal" in names


def test_profile_embed_without_api(make_user: object) -> None:
    user = make_goal_user(make_user(1, "alice"))
    embed = profile_embed(user, display_name="Alice")
    names = field_names(embed)
    assert "📈 LeetCode" in names
    assert "🎯 Goal" in names
    goal_value = next(field.value for field in embed.fields if field.name == "🎯 Goal")
    assert "stats unavailable" in goal_value


def test_daily_embed() -> None:
    daily = DailyChallenge(
        date="2026-11-02",
        title="Two Sum",
        title_slug="two-sum",
        difficulty="Easy",
        ac_rate=55.5,
        link="/problems/two-sum/",
    )
    embed = daily_embed(daily)
    assert embed.title == "🧩 Daily Challenge"
    assert "Two Sum" in (embed.description or "")
    assert embed.color.value == 0x00B8A3
    assert [field.name for field in embed.fields] == ["Difficulty", "Acceptance", "Solve"]


def test_goal_embeds_for_each_status() -> None:
    complete = calculate_goal_progress(
        50, 1, date(2026, 1, 1), baseline=100, current_solved=200, today=date(2026, 1, 15)
    )
    behind = calculate_goal_progress(
        100, 1, date(2026, 1, 1), baseline=0, current_solved=20, today=date(2026, 1, 16)
    )
    starting = calculate_goal_progress(
        100, 1, date(2026, 1, 1), baseline=0, current_solved=0, today=date(2026, 1, 1)
    )

    complete_embed = goal_embed(complete, "alice")
    assert complete_embed.color.value == SUCCESS_COLOR
    assert "Goal complete" in complete_embed.fields[1].value
    assert complete_embed.footer.text == "Update your baseline with /goal set whenever you restart."

    behind_embed = goal_embed(behind, "alice")
    assert behind_embed.color.value == WARNING_COLOR
    assert "Behind pace" in behind_embed.fields[1].value

    starting_embed = goal_embed(starting, "alice")
    assert starting_embed.color.value == INFO_COLOR
    assert "Just getting started" in starting_embed.fields[1].value


def test_leaderboard_embed_empty() -> None:
    embed = leaderboard_embed([], title="Server leaderboard", subtitle="All linked members")
    assert embed.title == "Server leaderboard"
    assert embed.description == "All linked members"
    assert embed.fields[0].name == "No data yet"


def test_leaderboard_embed_ranks_errors_and_contests() -> None:
    entries = [
        LeaderboardEntry(1, "alice", 542, contest_rating=1800.4),
        LeaderboardEntry(2, "bob", 0, error="unavailable"),
        LeaderboardEntry(3, "carol", 300),
        LeaderboardEntry(4, "dave", 200),
    ]
    embed = leaderboard_embed(entries, title="Cohort leaderboard")
    value = embed.fields[0].value
    assert "🥇 **alice**" in value
    assert "1,800 rating" in value
    assert "🥈 **bob** — _unavailable_" in value
    assert "🥉 **carol**" in value
    assert "`#04` **dave**" in value


def test_cohort_embed() -> None:
    cohort = Cohort(1, "Night Owls", 10, 100, 42, "2026-01-01T00:00:00+00:00")
    embed = cohort_embed(cohort, host_name="Alice", member_count=6, channel_mention="<#100>")
    assert embed.title == "📚 Night Owls"
    assert "Alice" in (embed.description or "")
    assert [field.name for field in embed.fields] == ["Members", "Channel", "Created"]
    assert embed.fields[1].value == "<#100>"
    assert embed.footer.text == "Use /cohort leaderboard to see how the group is doing."

    unlinked = cohort_embed(cohort, host_name="Alice", member_count=6, channel_mention=None)
    assert unlinked.fields[1].value == "Not linked"
