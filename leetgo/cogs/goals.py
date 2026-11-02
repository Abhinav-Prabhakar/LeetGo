"""Personal solving goals with pace tracking."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import goal_embed, info_embed, success_embed
from ..formatting import parse_date
from ..interactions import require_linked_user, send_error
from ..models import calculate_goal_progress
from ..views import ConfirmView

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.goals")


class Goals(commands.Cog):
    """Goal commands."""

    goal = app_commands.Group(name="goal", description="Set and track a solving goal")

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    @goal.command(name="set", description="Commit to a number of questions over a timeframe")
    @app_commands.describe(
        questions="How many questions you want to solve",
        months="How many months you want to take (1-60)",
    )
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def set_goal(self, interaction: discord.Interaction, questions: int, months: int) -> None:
        if not 1 <= questions <= 100_000:
            await send_error(
                interaction, "Invalid target", "Questions must be between 1 and 100,000."
            )
            return
        if not 1 <= months <= 60:
            await send_error(interaction, "Invalid timeframe", "Months must be between 1 and 60.")
            return
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        profile = await self.bot.lc.fetch_profile(user.lc_username, recent_limit=0)
        start = datetime.now(UTC).date()
        await self.bot.db.set_goal(
            interaction.user.id, questions, months, start, profile.total_solved
        )
        progress = calculate_goal_progress(
            target=questions,
            months=months,
            start_date=start,
            baseline=profile.total_solved,
            current_solved=profile.total_solved,
            today=start,
        )
        embed = goal_embed(progress, user.lc_username)
        embed.description = (
            f"Solve **{questions:,}** questions in **{months}** month"
            f"{'s' if months > 1 else ''}. Baseline: **{profile.total_solved:,}** solved today."
        )
        await interaction.edit_original_response(embed=embed)
        logger.info("User %s set goal %s/%s months", interaction.user.id, questions, months)

    @goal.command(name="view", description="Check your goal progress and pace")
    async def view_goal(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if not user.has_goal:
            await send_error(
                interaction, "No goal set", "Create one with `/goal set questions:100 months:3`."
            )
            return
        start = parse_date(user.goal_start_date)
        if start is None or user.goal_questions is None or user.goal_duration is None:
            await send_error(interaction, "Goal data is invalid", "Reset it with `/goal set`.")
            return
        await interaction.response.defer()
        profile = await self.bot.lc.fetch_profile(user.lc_username, recent_limit=0)
        progress = calculate_goal_progress(
            target=user.goal_questions,
            months=user.goal_duration,
            start_date=start,
            baseline=user.goal_baseline or 0,
            current_solved=profile.total_solved,
        )
        await interaction.followup.send(embed=goal_embed(progress, user.lc_username))

    @goal.command(name="clear", description="Remove your current goal")
    async def clear_goal(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if not user.has_goal:
            await send_error(interaction, "No goal set", "There is nothing to clear.")
            return
        view = ConfirmView(interaction.user.id, confirm_label="Clear goal", danger=True)
        await interaction.response.send_message(
            embed=info_embed(
                "Clear your goal?",
                f"Your target of **{user.goal_questions:,}** questions will be removed. "
                "Your solved history stays on LeetCode.",
            ),
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.value is not True:
            await interaction.edit_original_response(
                embed=info_embed("Cancelled", "Your goal is unchanged."), view=None
            )
            return
        await self.bot.db.clear_goal(interaction.user.id)
        await interaction.edit_original_response(
            embed=success_embed("Goal cleared", "Set a new one anytime with `/goal set`."),
            view=None,
        )
        logger.info("User %s cleared their goal", interaction.user.id)


async def setup(bot: LeetGo) -> None:
    """Register the goals cog."""
    await bot.add_cog(Goals(bot))
