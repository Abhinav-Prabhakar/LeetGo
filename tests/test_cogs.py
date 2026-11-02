"""Command-level tests with lightweight Discord doubles.

These tests exercise the command callbacks, database wiring and embed output
without a live gateway connection.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import discord
import pytest
from discord import app_commands

from leetgo.cogs.cohorts import CohortJoinView, Cohorts, cohort_name_autocomplete
from leetgo.cogs.goals import Goals
from leetgo.cogs.meta import Meta
from leetgo.cogs.profile import Profile
from leetgo.cogs.reminders import Reminders
from leetgo.cogs.roadmap import RoadmapCog, RoadmapProgressView
from leetgo.cogs.stats import Stats
from leetgo.db import Database
from leetgo.errors import ServiceUnavailableError
from leetgo.leaderboard import LeaderboardService
from leetgo.leetcode import ContestStat, DailyChallenge, DifficultyStat, UserProfile


class FakeUser:
    def __init__(
        self,
        user_id: int,
        name: str = "Alice",
        *,
        display_name: str = "Alice",
    ) -> None:
        self.id = user_id
        self.name = name
        self.display_name = display_name
        self.mention = f"<@{user_id}>"
        self.display_avatar = SimpleNamespace(url=f"https://example.com/{user_id}.png")
        self.dms: list[dict[str, Any]] = []
        self.dm_error: Exception | None = None

    def __str__(self) -> str:
        return f"{self.name}#1234"

    async def send(self, **kwargs: Any) -> None:
        if self.dm_error is not None:
            raise self.dm_error
        self.dms.append(kwargs)


class FakeChannel:
    def __init__(self, channel_id: int, name: str) -> None:
        self.id = channel_id
        self.name = name
        self.mention = f"<#{channel_id}>"
        self.messages: list[dict[str, Any]] = []
        self.deleted = False
        self.category: FakeCategory | None = None
        self.topic: str | None = None

    async def send(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    async def delete(self, reason: str | None = None) -> None:
        self.deleted = True
        self.delete_reason = reason


class FakeCategory:
    def __init__(self, category_id: int, name: str) -> None:
        self.id = category_id
        self.name = name


class FakeGuild:
    def __init__(self, guild_id: int = 10, name: str = "Test Server") -> None:
        self.id = guild_id
        self.name = name
        self.members: dict[int, FakeUser] = {}
        self.categories: list[FakeCategory] = []
        self.text_channels: list[FakeChannel] = []
        self._next_id = 1000
        self.me = SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_channels=True),
        )

    def get_member(self, user_id: int) -> FakeUser | None:
        return self.members.get(user_id)

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return next((channel for channel in self.text_channels if channel.id == channel_id), None)

    async def create_category(self, name: str, reason: str | None = None) -> FakeCategory:
        category = FakeCategory(self._next_id, name)
        self._next_id += 1
        self.categories.append(category)
        return category

    async def create_text_channel(
        self,
        name: str,
        *,
        category: FakeCategory | None = None,
        topic: str | None = None,
        reason: str | None = None,
    ) -> FakeChannel:
        channel = FakeChannel(self._next_id, name)
        self._next_id += 1
        channel.category = category
        channel.topic = topic
        self.text_channels.append(channel)
        return channel


class FakeResponse:
    def __init__(self) -> None:
        self._done = False
        self.messages: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, *args: Any, **kwargs: Any) -> None:
        self.messages.append({"args": args, **kwargs})
        self._done = True

    async def defer(self, **_: Any) -> None:
        self._done = True

    async def edit_message(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


class FakeInteraction:
    def __init__(
        self,
        user_id: int = 1,
        *,
        guild: FakeGuild | None = None,
        client: FakeBot | None = None,
    ) -> None:
        self.user = FakeUser(user_id)
        self.guild = guild or FakeGuild()
        self.guild_id = self.guild.id
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.original_response: list[dict[str, Any]] = []
        self.client = client
        self.command = SimpleNamespace(qualified_name="test")

    async def edit_original_response(self, **kwargs: Any) -> None:
        self.original_response.append(kwargs)


class FakeLeetCode:
    def __init__(self) -> None:
        self.profiles: dict[str, UserProfile] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[tuple[str, int]] = []
        self.daily = DailyChallenge(
            date="2026-11-02",
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            ac_rate=55.5,
            link="/problems/two-sum/",
        )

    async def fetch_profile(self, username: str, recent_limit: int = 5) -> UserProfile:
        self.calls.append((username, recent_limit))
        key = username.lower()
        if key in self.errors:
            raise self.errors[key]
        return self.profiles.get(key, make_profile(username))

    async def fetch_daily(self) -> DailyChallenge:
        return self.daily


def make_profile(username: str = "alice", solved: int = 300) -> UserProfile:
    return UserProfile(
        username=username,
        real_name="Alice Example",
        avatar_url="https://example.com/avatar.png",
        country="India",
        company=None,
        school=None,
        ranking=12345,
        reputation=10,
        star_rating=None,
        total_solved=solved,
        total_questions=3000,
        difficulty={
            "Easy": DifficultyStat(solved // 2, 800),
            "Medium": DifficultyStat(solved - solved // 2, 1800),
            "Hard": DifficultyStat(0, 400),
        },
        streak=12,
        total_active_days=50,
        contest=ContestStat(1700.0, 5),
    )


class FakeBot:
    def __init__(self, db: Database, lc: FakeLeetCode) -> None:
        self.db = db
        self.lc = lc
        self.settings = SimpleNamespace(
            default_timezone="UTC",
            leetcode_cache_ttl=300,
            max_leaderboard_users=50,
            reminder_poll_seconds=30,
            cohort_category="Cohorts",
            max_cohorts_per_guild=50,
        )
        self.version = "3.0.0"
        self.started_at = datetime.now(UTC) - timedelta(minutes=5)
        self.latency = 0.042
        self.guilds = [FakeGuild()]
        self.user = None
        self.leaderboards = LeaderboardService(lc)  # type: ignore[arg-type]
        self._users: dict[int, FakeUser] = {}

    def get_user(self, user_id: int) -> FakeUser | None:
        return self._users.get(user_id)

    async def fetch_user(self, user_id: int) -> FakeUser | None:
        return self._users.get(user_id)


@pytest.fixture
def lc() -> FakeLeetCode:
    return FakeLeetCode()


@pytest.fixture
def bot(db: Database, lc: FakeLeetCode) -> FakeBot:
    return FakeBot(db, lc)


@pytest.fixture
def interaction() -> FakeInteraction:
    return FakeInteraction()


async def link(bot: FakeBot, user_id: int = 1, username: str = "alice") -> None:
    await bot.db.link_user(user_id, f"user{user_id}", username)


async def test_meta_help(bot: FakeBot, interaction: FakeInteraction) -> None:
    cog = Meta(bot)  # type: ignore[arg-type]
    await Meta.help_command.callback(cog, interaction)  # type: ignore[arg-type]

    message = interaction.response.messages[0]
    embed = message["embed"]
    assert message["ephemeral"] is True
    assert embed.title == "🧭 LeetGo command guide"
    assert len(embed.fields) == 6
    assert "v3.0.0" in embed.footer.text


async def test_meta_ping_and_about(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Meta(bot)  # type: ignore[arg-type]
    await Meta.ping.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.is_done()
    ping_embed = interaction.original_response[0]["embed"]
    assert ping_embed.title == "🏓 Pong"
    assert {"Gateway", "Database", "Uptime", "Users"} <= {field.name for field in ping_embed.fields}

    interaction2 = FakeInteraction()
    await Meta.about.callback(cog, interaction2)  # type: ignore[arg-type]
    about_embed = interaction2.response.messages[0]["embed"]
    assert about_embed.title == "⚡ LeetGo"
    assert "Version" in {field.name for field in about_embed.fields}
    assert about_embed.url.startswith("https://github.com/Abhinav-Prabhakar/LeetGo")

    bot.user = SimpleNamespace(id=123456789)
    invite = cog._invite_url()
    assert invite is not None
    assert "permissions=85008" in invite
    assert "scope=bot%20applications.commands" in invite


async def test_profile_set_username(bot: FakeBot, interaction: FakeInteraction) -> None:
    bot.lc.profiles["alice_lc"] = make_profile("alice_lc")
    cog = Profile(bot)  # type: ignore[arg-type]
    await Profile.set_username.callback(cog, interaction, username=" Alice_LC ")  # type: ignore[arg-type]

    user = await bot.db.get_user(1)
    assert user is not None and user.lc_username == "alice_lc"
    assert interaction.response.is_done()
    embed = interaction.original_response[0]["embed"]
    assert embed.title == "✅ LeetCode account linked"


async def test_profile_set_username_rejects_invalid(
    bot: FakeBot, interaction: FakeInteraction
) -> None:
    cog = Profile(bot)  # type: ignore[arg-type]
    await Profile.set_username.callback(cog, interaction, username="bad name")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Invalid username"
    assert await bot.db.get_user(1) is None


async def test_profile_lookup_and_fallback(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Profile(bot)  # type: ignore[arg-type]
    await Profile.profile.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "👤 Alice"

    bot.lc.errors["alice"] = ServiceUnavailableError("down")
    interaction2 = FakeInteraction()
    await Profile.profile.callback(cog, interaction2)  # type: ignore[arg-type]
    names = {field.name for field in interaction2.response.messages[0]["embed"].fields}
    assert "📈 LeetCode" in names


async def test_profile_missing_accounts(bot: FakeBot, interaction: FakeInteraction) -> None:
    cog = Profile(bot)  # type: ignore[arg-type]
    await Profile.profile.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No account linked"

    other = FakeUser(2, "Bob", display_name="Bob")
    interaction2 = FakeInteraction()
    await Profile.profile.callback(cog, interaction2, member=other)  # type: ignore[arg-type]
    assert interaction2.response.messages[-1]["embed"].title == "Not linked"


async def test_profile_unlink_blocked_while_hosting(
    bot: FakeBot, interaction: FakeInteraction
) -> None:
    await link(bot)
    await bot.db.create_cohort("Hosted", 10, 100, 1)
    cog = Profile(bot)  # type: ignore[arg-type]
    await Profile.unlink.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "You still host a cohort"
    assert await bot.db.get_user(1) is not None


async def test_profile_unlink_confirmation_paths(
    bot: FakeBot, interaction: FakeInteraction, monkeypatch: pytest.MonkeyPatch
) -> None:
    await link(bot)
    cog = Profile(bot)  # type: ignore[arg-type]

    async def cancel(_: object) -> None:
        _.value = False

    monkeypatch.setattr("leetgo.cogs.profile.ConfirmView.wait", cancel)
    await Profile.unlink.callback(cog, interaction)  # type: ignore[arg-type]
    assert "Unlink cancelled" in interaction.original_response[-1]["embed"].title
    assert await bot.db.get_user(1) is not None

    async def confirm(_: object) -> None:
        _.value = True

    monkeypatch.setattr("leetgo.cogs.profile.ConfirmView.wait", confirm)
    interaction2 = FakeInteraction()
    await Profile.unlink.callback(cog, interaction2)  # type: ignore[arg-type]
    assert interaction2.original_response[-1]["embed"].title == "Account unlinked"
    assert await bot.db.get_user(1) is None


async def test_goal_set_validation_and_success(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Goals(bot)  # type: ignore[arg-type]
    await Goals.set_goal.callback(cog, interaction, questions=0, months=1)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Invalid target"

    interaction_invalid = FakeInteraction()
    await Goals.set_goal.callback(cog, interaction_invalid, questions=100, months=0)  # type: ignore[arg-type]
    assert interaction_invalid.response.messages[0]["embed"].title == "Invalid timeframe"

    interaction2 = FakeInteraction()
    await Goals.set_goal.callback(cog, interaction2, questions=100, months=3)  # type: ignore[arg-type]
    user = await bot.db.get_user(1)
    assert user is not None and user.goal_questions == 100
    assert user.goal_baseline == 300
    assert "Baseline" in (interaction2.original_response[0]["embed"].description or "")


async def test_goal_view_and_clear(
    bot: FakeBot, interaction: FakeInteraction, monkeypatch: pytest.MonkeyPatch
) -> None:
    await link(bot)
    cog = Goals(bot)  # type: ignore[arg-type]
    await Goals.view_goal.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No goal set"

    await bot.db.set_goal(1, 100, 1, date.today(), 300)
    interaction2 = FakeInteraction()
    await Goals.view_goal.callback(cog, interaction2)  # type: ignore[arg-type]
    assert interaction2.followup.messages[0]["embed"].title == "🎯 alice's Goal"

    async def confirm(_: object) -> None:
        _.value = True

    monkeypatch.setattr("leetgo.cogs.goals.ConfirmView.wait", confirm)
    interaction3 = FakeInteraction()
    await Goals.clear_goal.callback(cog, interaction3)  # type: ignore[arg-type]
    assert interaction3.original_response[-1]["embed"].title == "Goal cleared"


async def test_goal_clear_confirmation(bot: FakeBot, monkeypatch: pytest.MonkeyPatch) -> None:
    await link(bot)
    await bot.db.set_goal(1, 100, 1, date.today(), 300)
    cog = Goals(bot)  # type: ignore[arg-type]

    async def confirm(_: object) -> None:
        _.value = True

    monkeypatch.setattr("leetgo.cogs.goals.ConfirmView.wait", confirm)
    interaction = FakeInteraction()
    await Goals.clear_goal.callback(cog, interaction)  # type: ignore[arg-type]
    user = await bot.db.get_user(1)
    assert user is not None and not user.has_goal
    assert interaction.original_response[-1]["embed"].title == "Goal cleared"


async def test_reminder_validation_set_view_remove(
    bot: FakeBot, interaction: FakeInteraction
) -> None:
    await link(bot)
    cog = Reminders(bot)  # type: ignore[arg-type]

    await Reminders.set_reminder.callback(  # type: ignore[arg-type]
        cog, interaction, hour=20, minute=0, timezone="Mars/Olympus"
    )
    assert interaction.response.messages[0]["embed"].title == "Invalid timezone"

    await Reminders.set_reminder.callback(  # type: ignore[arg-type]
        cog, interaction, hour=20, minute=0, timezone="Asia/Kolkata"
    )
    user = await bot.db.get_user(1)
    assert user is not None and user.has_reminder
    assert user.timezone == "Asia/Kolkata"

    interaction2 = FakeInteraction()
    await Reminders.view_reminder.callback(cog, interaction2)  # type: ignore[arg-type]
    assert interaction2.response.messages[0]["embed"].title == "⏰ Your reminder"

    interaction3 = FakeInteraction()
    await Reminders.remove_reminder.callback(cog, interaction3)  # type: ignore[arg-type]
    user = await bot.db.get_user(1)
    assert user is not None and not user.has_reminder
    assert interaction3.response.messages[0]["embed"].title == "🔕 Reminders off"

    interaction4 = FakeInteraction()
    await Reminders.remove_reminder.callback(cog, interaction4)  # type: ignore[arg-type]
    assert interaction4.response.messages[-1]["embed"].title == "No reminder set"


async def test_reminder_view_without_schedule(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Reminders(bot)  # type: ignore[arg-type]
    await Reminders.view_reminder.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No reminder set"


async def test_reminder_test_dm(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Reminders(bot)  # type: ignore[arg-type]
    await Reminders.test_reminder.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.user.dms[0]["embed"].title == "⏰ Test reminder"
    assert interaction.original_response[-1]["embed"].title == "Test sent"


async def test_reminder_test_dm_forbidden(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    interaction.user.dm_error = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "blocked"
    )
    cog = Reminders(bot)  # type: ignore[arg-type]
    await Reminders.test_reminder.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.original_response[-1]["embed"].title == "Could not send a DM"


async def test_reminder_scheduler_is_idempotent(
    bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    await link(bot)
    await bot.db.set_reminder(1, 20, 0, "UTC")
    bot._users[1] = FakeUser(1)
    cog = Reminders(bot)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "leetgo.cogs.reminders.is_due",
        lambda *_: (True, "2026-11-02"),
    )
    await Reminders._tick(cog)
    assert len(bot._users[1].dms) == 1
    assert await bot.db.was_reminder_sent(1, "2026-11-02") is True

    await Reminders._tick(cog)
    assert len(bot._users[1].dms) == 1


async def test_roadmap_selection_and_progress(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = RoadmapCog(bot)  # type: ignore[arg-type]

    await RoadmapCog.roadmap.callback(cog, interaction)  # type: ignore[arg-type]
    message = interaction.response.messages[0]
    assert "Choose your learning path" in message["embed"].title
    assert message["view"] is not None

    await RoadmapCog._select(cog, interaction, "Beginner")  # type: ignore[arg-type]
    user = await bot.db.get_user(1)
    assert user is not None and user.roadmap == "Beginner"
    assert interaction.response.edits[-1]["embed"].title.endswith("selected")

    await RoadmapCog._select(cog, interaction, "Beginner")  # type: ignore[arg-type]
    assert "already active" in interaction.response.edits[-1]["embed"].title

    interaction2 = FakeInteraction()
    await RoadmapCog.roadmap_progress.callback(cog, interaction2)  # type: ignore[arg-type]
    message = interaction2.response.messages[0]
    assert message["view"] is not None

    view = message["view"]
    assert isinstance(view, RoadmapProgressView)
    button = view._buttons["Arrays & Hashing"]
    await button.callback(interaction2)  # type: ignore[misc]
    user = await bot.db.get_user(1)
    assert user is not None and "Arrays & Hashing" in user.roadmap_progress


async def test_roadmap_requires_link_and_selection(
    bot: FakeBot, interaction: FakeInteraction
) -> None:
    cog = RoadmapCog(bot)  # type: ignore[arg-type]
    await RoadmapCog.roadmap.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No LeetCode account linked"

    interaction2 = FakeInteraction()
    await RoadmapCog.roadmap_progress.callback(cog, interaction2)  # type: ignore[arg-type]
    assert interaction2.response.messages[0]["embed"].title == "No LeetCode account linked"


async def test_roadmap_progress_requires_roadmap(
    bot: FakeBot, interaction: FakeInteraction
) -> None:
    await link(bot)
    cog = RoadmapCog(bot)  # type: ignore[arg-type]
    await RoadmapCog.roadmap_progress.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No roadmap selected"


async def test_stats_and_daily(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    cog = Stats(bot)  # type: ignore[arg-type]
    await Stats.stats.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.followup.messages[0]["embed"].title == "📊 alice"

    interaction2 = FakeInteraction()
    await Stats.daily.callback(cog, interaction2)  # type: ignore[arg-type]
    assert interaction2.followup.messages[0]["embed"].title == "🧩 Daily Challenge"
    assert interaction2.followup.messages[0]["view"] is not None


async def test_stats_missing_account(bot: FakeBot, interaction: FakeInteraction) -> None:
    cog = Stats(bot)  # type: ignore[arg-type]
    await Stats.stats.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No LeetCode account linked"


async def test_compare(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    bot.lc.profiles["alice"] = make_profile("alice", 300)
    bot.lc.profiles["bob"] = make_profile("bob", 400)
    cog = Stats(bot)  # type: ignore[arg-type]

    await Stats.compare.callback(cog, interaction, first=interaction.user, second=interaction.user)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Pick two different members"

    interaction2 = FakeInteraction()
    await Stats.compare.callback(cog, interaction2, first=interaction.user, second=FakeUser(2))  # type: ignore[arg-type]
    embed = interaction2.followup.messages[0]["embed"]
    assert embed.title == "⚔️ Head to head"
    assert "bob" in embed.description


async def test_compare_requires_linked_members(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot, 1, "alice")
    cog = Stats(bot)  # type: ignore[arg-type]
    other = FakeUser(2)
    await Stats.compare.callback(cog, interaction, first=interaction.user, second=other)  # type: ignore[arg-type]
    assert interaction.response.messages[-1]["embed"].title == "That member is not linked"


async def test_leaderboard_cohort_and_server(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    await bot.db.create_cohort("Night Owls", 10, 100, 1)
    await bot.db.set_user_cohort(2, 1)
    bot.guilds[0].members = {1: FakeUser(1), 2: FakeUser(2)}
    cog = Stats(bot)  # type: ignore[arg-type]

    await Stats.leaderboard.callback(cog, interaction, scope=None)  # type: ignore[arg-type]
    embed = interaction.followup.messages[0]["embed"]
    assert embed.title == "🏆 Night Owls leaderboard"

    interaction2 = FakeInteraction(guild=bot.guilds[0])
    scope = app_commands.Choice(name="Whole server", value="Server")
    await Stats.leaderboard.callback(cog, interaction2, scope=scope)  # type: ignore[arg-type]
    assert interaction2.followup.messages[0]["embed"].title == "🏆 Test Server leaderboard"


async def test_leaderboard_errors(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot, 1, "alice")
    cog = Stats(bot)  # type: ignore[arg-type]
    await Stats.leaderboard.callback(cog, interaction, scope=None)  # type: ignore[arg-type]
    assert interaction.response.messages[-1]["embed"].title == "You're not in a cohort"

    interaction2 = FakeInteraction()
    await Stats.leaderboard.callback(cog, interaction2)  # type: ignore[arg-type]
    # The user is linked now, so this reports the missing cohort rather than linking.
    assert interaction2.response.messages[-1]["embed"].title == "You're not in a cohort"


async def test_compare_embed_tie_uses_streak() -> None:
    left = make_profile("alice", 300)
    right = make_profile("bob", 300)
    embed = Stats._compare_embed(Stats.__new__(Stats), left, right)
    assert "tie" in embed.fields[-2].value.lower()
    assert "Verdict" in {field.name for field in embed.fields}


# ---------------------------------------------------------------------------
# Cohorts — the most stateful command surface
# ---------------------------------------------------------------------------


async def test_cohort_create_success(bot: FakeBot, interaction: FakeInteraction) -> None:
    await link(bot)
    guild = bot.guilds[0]
    interaction = FakeInteraction(guild=guild)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    await Cohorts.create.callback(cog, interaction, name="Night Owls")  # type: ignore[arg-type]

    cohort = await bot.db.get_cohort_by_name(10, "night owls")
    assert cohort is not None
    assert cohort.channel_id is not None
    assert guild.categories[0].name == "Cohorts"
    channel = guild.get_channel(cohort.channel_id)
    assert channel is not None
    assert channel.name == "night-owls"
    assert channel.messages[0]["embed"].title.startswith("🎉")
    assert interaction.original_response[-1]["embed"].title == "✅ Cohort created"
    user = await bot.db.get_user(1)
    assert user is not None and user.cohort_id == cohort.cohort_id


async def test_cohort_create_validation(bot: FakeBot) -> None:
    guild = bot.guilds[0]
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="   ")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Invalid name"

    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="x" * 91)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Invalid name"

    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="Valid")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No LeetCode account linked"


async def test_cohort_create_duplicate_and_limit(
    bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    guild = bot.guilds[0]
    await bot.db.create_cohort("Taken", 10, 100, 2)
    guild.text_channels.append(FakeChannel(100, "taken"))
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="Taken")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Name already used"

    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.create.callback(cog, interaction, name="New")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "You're already in a cohort"

    # A host who is free, but the guild is at its cohort limit.
    await bot.db.clear_user_cohort(2)
    bot.settings.max_cohorts_per_guild = 1
    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="Another")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Cohort limit reached"


async def test_cohort_create_permission_and_collision(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    guild = bot.guilds[0]
    cog = Cohorts(bot)  # type: ignore[arg-type]

    guild.me.guild_permissions.manage_channels = False
    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="No Perms")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "I need Manage Channels"
    guild.me.guild_permissions.manage_channels = True

    guild.text_channels.append(FakeChannel(500, "taken-name"))
    interaction = FakeInteraction(guild=guild)
    await Cohorts.create.callback(cog, interaction, name="Taken Name")  # type: ignore[arg-type]
    assert interaction.followup.messages[0]["embed"].title == "Channel already exists"


async def test_cohort_join_by_name_and_menu(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    await link(bot, 3, "carol")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.join.callback(cog, interaction, name="Night Owls")  # type: ignore[arg-type]
    user = await bot.db.get_user(2)
    assert user is not None and user.cohort_id == cohort.cohort_id
    assert interaction.original_response[-1]["embed"].title == "✅ Joined cohort"

    interaction = FakeInteraction(3, guild=guild)
    await Cohorts.join.callback(cog, interaction, name=None)  # type: ignore[arg-type]
    message = interaction.response.messages[0]
    view = message["view"]
    assert isinstance(view, CohortJoinView)
    assert await view.interaction_check(interaction) is True
    view.children[0]._values = [str(cohort.cohort_id)]
    await view._on_select(interaction)
    user = await bot.db.get_user(3)
    assert user is not None and user.cohort_id == cohort.cohort_id
    assert interaction.response.edits[-1]["embed"].title == "✅ Joined cohort"


async def test_cohort_join_errors(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    guild = bot.guilds[0]
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.join.callback(cog, interaction, name=None)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No cohorts yet"

    await bot.db.create_cohort("Night Owls", 10, 100, 1)
    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.join.callback(cog, interaction, name="Missing")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Cohort not found"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.join.callback(cog, interaction, name="Night Owls")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Already in a cohort"

    interaction = FakeInteraction(9, guild=guild)
    await Cohorts.join.callback(cog, interaction, name="Night Owls")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No LeetCode account linked"


async def test_cohort_leave_member_host_and_delete(
    bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    await link(bot, 3, "carol")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    channel = FakeChannel(100, "night-owls")
    guild.text_channels.append(channel)
    await bot.db.set_user_cohort(2, cohort.cohort_id)
    await bot.db.set_user_cohort(3, cohort.cohort_id)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(9, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Not in a cohort"

    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "👋 Left cohort"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "You're the host"

    interaction = FakeInteraction(3, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "👋 Left cohort"

    async def cancel(_: object) -> None:
        _.value = False

    monkeypatch.setattr("leetgo.cogs.cohorts.ConfirmView.wait", cancel)
    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.original_response[-1]["embed"].title == "Cancelled"

    async def confirm(_: object) -> None:
        _.value = True

    monkeypatch.setattr("leetgo.cogs.cohorts.ConfirmView.wait", confirm)
    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leave.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.original_response[-1]["embed"].title == "Cohort deleted"
    assert channel.deleted is True
    assert await bot.db.get_cohort(cohort.cohort_id) is None


async def test_cohort_info_and_list(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    guild = bot.guilds[0]
    guild.members[1] = FakeUser(1)
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.info.callback(cog, interaction)  # type: ignore[arg-type]
    embed = interaction.response.messages[0]["embed"]
    assert embed.title == "📚 Night Owls"
    assert "Roster" in {field.name for field in embed.fields}

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.info.callback(cog, interaction, name="Missing")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Cohort not found"

    interaction = FakeInteraction(9, guild=guild)
    await Cohorts.info.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "You're not in a cohort"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.list_cohorts.callback(cog, interaction)  # type: ignore[arg-type]
    embed = interaction.response.messages[0]["embed"]
    assert "Night Owls" in {field.name for field in embed.fields}

    await bot.db.delete_cohort(cohort.cohort_id)
    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.list_cohorts.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "No cohorts yet"


async def test_cohort_leaderboard(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    await bot.db.set_user_cohort(2, cohort.cohort_id)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leaderboard.callback(cog, interaction)  # type: ignore[arg-type]
    embed = interaction.followup.messages[0]["embed"]
    assert embed.title == "🏆 Night Owls leaderboard"

    await bot.db.clear_user_cohort(1)
    await bot.db.clear_user_cohort(2)
    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leaderboard.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "You're not in a cohort"


async def test_cohort_leaderboard_empty(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Empty", 10, 100, 1)
    await bot.db.clear_user_cohort(1)
    cog = Cohorts(bot)  # type: ignore[arg-type]
    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.leaderboard.callback(cog, interaction, name="Empty")  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Empty cohort"
    assert await bot.db.get_cohort(cohort.cohort_id) is not None


async def test_cohort_delete_and_transfer(bot: FakeBot, monkeypatch: pytest.MonkeyPatch) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    await link(bot, 3, "carol")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    channel = FakeChannel(100, "night-owls")
    guild.text_channels.append(channel)
    await bot.db.set_user_cohort(2, cohort.cohort_id)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.delete.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Host only"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.transfer.callback(cog, interaction, member=FakeUser(1))  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Pick someone else"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.transfer.callback(cog, interaction, member=FakeUser(3))  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Not a member"

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.transfer.callback(cog, interaction, member=FakeUser(2))  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Ownership transferred"
    updated = await bot.db.get_cohort(cohort.cohort_id)
    assert updated is not None and updated.host_id == 2

    interaction = FakeInteraction(1, guild=guild)
    await Cohorts.delete.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.response.messages[0]["embed"].title == "Host only"

    async def confirm(_: object) -> None:
        _.value = True

    monkeypatch.setattr("leetgo.cogs.cohorts.ConfirmView.wait", confirm)
    interaction = FakeInteraction(2, guild=guild)
    await Cohorts.delete.callback(cog, interaction)  # type: ignore[arg-type]
    assert interaction.original_response[-1]["embed"].title == "Cohort deleted"
    assert channel.deleted is True
    assert await bot.db.get_cohort(cohort.cohort_id) is None


async def test_cohort_autocomplete_and_member_remove(bot: FakeBot) -> None:
    await link(bot, 1, "alice")
    await link(bot, 2, "bob")
    guild = bot.guilds[0]
    cohort = await bot.db.create_cohort("Night Owls", 10, 100, 1)
    await bot.db.set_user_cohort(2, cohort.cohort_id)
    cog = Cohorts(bot)  # type: ignore[arg-type]

    interaction = FakeInteraction(1, guild=guild, client=bot)
    choices = await cohort_name_autocomplete(interaction, "night")  # type: ignore[arg-type]
    assert [choice.value for choice in choices] == ["Night Owls"]
    assert await cohort_name_autocomplete(interaction, "none") == []

    member = SimpleNamespace(id=2, bot=False, guild=guild)
    await cog.on_member_remove(member)  # type: ignore[arg-type]
    user = await bot.db.get_user(2)
    assert user is not None and user.cohort_id is None

    host = SimpleNamespace(id=1, bot=False, guild=guild)
    await cog.on_member_remove(host)  # type: ignore[arg-type]
    assert await bot.db.get_cohort(cohort.cohort_id) is None


# ---------------------------------------------------------------------------
# Bot lifecycle / error mapping and logging
# ---------------------------------------------------------------------------


async def test_bot_construction_and_tree_error_mapping() -> None:
    from discord.ext import commands as dcommands

    from leetgo.bot import LeetGo
    from leetgo.config import Settings
    from leetgo.errors import (
        InvalidUsernameError,
        LeetCodeError,
        RateLimitedError,
        ServiceUnavailableError,
        UsernameTakenError,
        UserNotFoundError,
    )

    settings = Settings(bot_token="test-token", _env_file=None, log_file=None)
    bot = LeetGo(settings)
    try:
        assert bot.version == "3.0.0"
        assert bot.settings is settings
        assert bot.db.path.name == "leetgo.db"
        assert bot.lc.cache_ttl == settings.leetcode_cache_ttl

        cooldown = app_commands.CommandOnCooldown(dcommands.Cooldown(1, 30.0), 12.5)
        cases: list[tuple[Exception, str]] = [
            (cooldown, "Slow down ⏳"),
            (app_commands.MissingPermissions(["manage_channels"]), "Missing permissions"),
            (app_commands.BotMissingPermissions(["manage_channels"]), "I need more permissions"),
            (app_commands.NoPrivateMessage(), "Server only"),
            (UserNotFoundError("missing"), "LeetCode user not found"),
            (InvalidUsernameError("bad"), "Invalid username"),
            (UsernameTakenError("taken"), "Username already linked"),
            (RateLimitedError(12.0), "LeetCode is rate limiting us"),
            (ServiceUnavailableError("down"), "LeetCode is unavailable"),
            (LeetCodeError("nope"), "LeetCode error"),
        ]
        for error, expected in cases:
            interaction = FakeInteraction()
            await bot.on_tree_error(interaction, error)  # type: ignore[arg-type]
            messages = interaction.response.messages + interaction.followup.messages
            assert messages, expected
            assert messages[-1]["embed"].title == expected

        forbidden = FakeInteraction()
        await bot.on_tree_error(
            forbidden,  # type: ignore[arg-type]
            discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no"),
        )
        assert forbidden.response.messages[-1]["embed"].title == "I'm missing permissions"

        unexpected = FakeInteraction()
        await bot.on_tree_error(  # type: ignore[arg-type]
            unexpected, RuntimeError("boom")
        )
        embed = unexpected.response.messages[-1]["embed"]
        assert embed.title == "Something went wrong"
        assert "Reference:" in embed.description
    finally:
        await bot.close()


async def test_logging_setup_plain_and_json(tmp_path: Any) -> None:
    import logging

    from leetgo.logging_setup import JsonFormatter, setup_logging

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    try:
        setup_logging("DEBUG", None, json_logs=False)
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JsonFormatter)

        log_file = tmp_path / "logs" / "leetgo.log"
        setup_logging("INFO", log_file, json_logs=True)
        assert len(root.handlers) == 2
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        logging.getLogger("test").info(
            "hello", extra={"guild_id": 10, "command": "stats", "error_id": "abc"}
        )
        for handler in root.handlers:
            handler.flush()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["message"] == "hello"
        assert payload["guild_id"] == 10
        assert payload["command"] == "stats"
        assert payload["error_id"] == "abc"
        assert payload["level"] == "INFO"
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = old_handlers
        root.setLevel(old_level)
