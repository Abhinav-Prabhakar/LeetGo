"""LeetCode statistics, daily challenge, comparisons and leaderboards."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import DIFFICULTY_EMOJI
from ..embeds import base_embed, daily_embed, leaderboard_embed, stats_embed
from ..formatting import format_number, format_percent, progress_bar
from ..interactions import require_linked_user, send_error
from ..leetcode import UserProfile
from ..models import UserRecord
from ..views import LinkView

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.stats")


class Stats(commands.Cog):
    """Show LeetCode progress and friendly competition."""

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    @app_commands.command(name="stats", description="Show LeetCode statistics and progress")
    @app_commands.describe(member="Member to inspect (defaults to you)")
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def stats(
        self, interaction: discord.Interaction, member: discord.User | None = None
    ) -> None:
        target = member or interaction.user
        user = await require_linked_user(interaction, self.bot.db, user_id=target.id)
        if user is None:
            return
        await interaction.response.defer()
        profile = await self.bot.lc.fetch_profile(user.lc_username)
        embed = stats_embed(profile, user)
        await interaction.followup.send(embed=embed)
        logger.info("Rendered stats for %s", user.lc_username)

    # ------------------------------------------------------------------
    # Daily
    # ------------------------------------------------------------------
    @app_commands.command(name="daily", description="Show today's LeetCode daily challenge")
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        daily = await self.bot.lc.fetch_daily()
        await interaction.followup.send(
            embed=daily_embed(daily), view=LinkView(daily.url, "Solve on LeetCode")
        )

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    @app_commands.command(name="compare", description="Compare two linked members")
    @app_commands.describe(first="First member", second="Second member")
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def compare(
        self,
        interaction: discord.Interaction,
        first: discord.User,
        second: discord.User,
    ) -> None:
        if first.id == second.id:
            await send_error(interaction, "Pick two different members", "They must be different.")
            return
        first_user = await require_linked_user(interaction, self.bot.db, user_id=first.id)
        if first_user is None:
            return
        second_user = await require_linked_user(interaction, self.bot.db, user_id=second.id)
        if second_user is None:
            return

        await interaction.response.defer()
        results = await asyncio.gather(
            self.bot.lc.fetch_profile(first_user.lc_username),
            self.bot.lc.fetch_profile(second_user.lc_username),
        )
        left, right = results
        embed = self._compare_embed(left, right)
        await interaction.followup.send(embed=embed)

    def _compare_embed(self, left: UserProfile, right: UserProfile) -> discord.Embed:
        def column(profile: UserProfile) -> str:
            return (
                f"**Total** {format_number(profile.total_solved)}\n"
                f"{DIFFICULTY_EMOJI['Easy']} {profile.easy.solved} • "
                f"{DIFFICULTY_EMOJI['Medium']} {profile.medium.solved} • "
                f"{DIFFICULTY_EMOJI['Hard']} {profile.hard.solved}\n"
                f"🔥 {profile.streak}d streak\n"
                f"🏆 {('#' + format_number(profile.ranking)) if profile.ranking else '—'}\n"
                f"⚔️ {format_number(round(profile.contest.rating)) if profile.contest else '—'}"
            )

        embed = base_embed(
            title="⚔️ Head to head",
            description=f"**{left.username}** vs **{right.username}**",
        )
        embed.add_field(name=f"👤 {left.username}", value=column(left), inline=True)
        embed.add_field(name=f"👤 {right.username}", value=column(right), inline=True)

        if left.total_solved == right.total_solved:
            verdict = "It's a tie on total solved — check the streak tiebreaker!"
            left_score = left.streak
            right_score = right.streak
        else:
            left_score = left.total_solved
            right_score = right.total_solved
        winner = left.username if left_score >= right_score else right.username
        if left.total_solved != right.total_solved:
            verdict = f"**{winner}** leads on total solved."
        embed.add_field(name="Verdict", value=verdict, inline=False)
        embed.add_field(
            name="Overall progress",
            value=(
                f"**{left.username}** {progress_bar(left.overall_percent)} "
                f"{format_percent(left.overall_percent)}\n"
                f"**{right.username}** {progress_bar(right.overall_percent)} "
                f"{format_percent(right.overall_percent)}"
            ),
            inline=False,
        )
        return embed

    # ------------------------------------------------------------------
    # Leaderboard
    # ------------------------------------------------------------------
    @app_commands.command(name="leaderboard", description="Rank linked members by problems solved")
    @app_commands.describe(scope="Rank your cohort or the whole server")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="My cohort", value="Cohort"),
            app_commands.Choice(name="Whole server", value="Server"),
        ]
    )
    @app_commands.guild_only()
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def leaderboard(
        self, interaction: discord.Interaction, scope: app_commands.Choice[str] | None = None
    ) -> None:
        assert interaction.guild is not None
        selected = scope.value if scope else "Cohort"
        requester = await self.bot.db.get_user(interaction.user.id)
        if requester is None:
            await send_error(
                interaction, "No account linked", "Use `/set-username` before joining a board."
            )
            return

        if selected == "Cohort":
            if requester.cohort_id is None:
                await send_error(
                    interaction,
                    "You're not in a cohort",
                    "Join one with `/cohort join`, or use `/leaderboard scope: Whole server`.",
                )
                return
            cohort = await self.bot.db.get_cohort(requester.cohort_id)
            if cohort is None:
                await send_error(interaction, "Cohort not found", "It may have been deleted.")
                return
            members = await self.bot.db.list_cohort_members(cohort.cohort_id)
            title = f"🏆 {cohort.name} leaderboard"
            subtitle = f"{len(members)} members • cached for 5 minutes"
        else:
            members = await self._guild_members(interaction.guild)
            title = f"🏆 {interaction.guild.name} leaderboard"
            subtitle = f"{len(members)} linked members • cached for 5 minutes"

        members = members[: self.bot.settings.max_leaderboard_users]
        if not members:
            await send_error(interaction, "Nobody to rank yet", "Invite friends to link accounts!")
            return

        await interaction.response.defer()
        entries = await self.bot.leaderboards.fetch(members)
        await interaction.followup.send(
            embed=leaderboard_embed(entries[:10], title=title, subtitle=subtitle)
        )

    async def _guild_members(self, guild: discord.Guild) -> list[UserRecord]:
        linked = await self.bot.db.list_linked_users(
            limit=max(self.bot.settings.max_leaderboard_users * 4, 100)
        )
        return [
            user
            for user in linked
            if user.user_id is not None and guild.get_member(user.user_id) is not None
        ]


async def setup(bot: LeetGo) -> None:
    """Register the stats cog."""
    await bot.add_cog(Stats(bot))
