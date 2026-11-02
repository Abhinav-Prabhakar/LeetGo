"""Profile linking commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import error_embed, profile_embed, success_embed
from ..errors import InvalidUsernameError, LeetCodeError
from ..interactions import display_name_for, member_avatar, send_error
from ..leetcode import UserProfile, validate_username
from ..views import ConfirmView

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.profile")


class Profile(commands.Cog):
    """Link, inspect and unlink LeetCode accounts."""

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    @app_commands.command(name="set-username", description="Link or update your LeetCode username")
    @app_commands.describe(username="Your LeetCode username (not your display name)")
    @app_commands.checks.cooldown(3, 60.0, key=lambda i: i.user.id)
    async def set_username(self, interaction: discord.Interaction, username: str) -> None:
        try:
            cleaned = validate_username(username)
        except InvalidUsernameError as exc:
            await send_error(interaction, "Invalid username", str(exc))
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        profile = await self.bot.lc.fetch_profile(cleaned)
        user = await self.bot.db.link_user(
            interaction.user.id,
            str(interaction.user),
            profile.username or cleaned,
            timezone=self.bot.settings.default_timezone,
        )
        embed = success_embed(
            "✅ LeetCode account linked",
            f"**{user.lc_username}** is now connected to {interaction.user.mention}.",
        )
        if profile.avatar_url:
            embed.set_thumbnail(url=profile.avatar_url)
        embed.add_field(name="Solved", value=f"{profile.total_solved:,}", inline=True)
        embed.add_field(name="Streak", value=f"{profile.streak} days", inline=True)
        embed.add_field(
            name="Rank",
            value=f"#{profile.ranking:,}" if profile.ranking else "—",
            inline=True,
        )
        embed.set_footer(text="Use /stats for the full card • /roadmap to pick a path")
        await interaction.edit_original_response(embed=embed)
        logger.info("Linked %s to LeetCode user %s", interaction.user.id, user.lc_username)

    @app_commands.command(name="profile", description="Show a member's LeetGo profile")
    @app_commands.describe(member="Member to inspect (defaults to you)")
    async def profile(
        self, interaction: discord.Interaction, member: discord.User | None = None
    ) -> None:
        target = member or interaction.user
        user = await self.bot.db.get_user(target.id)
        if user is None:
            if target.id == interaction.user.id:
                await send_error(
                    interaction,
                    "No account linked",
                    "Use `/set-username` to connect your LeetCode account.",
                )
            else:
                await send_error(
                    interaction, "Not linked", f"{target.mention} has not linked LeetCode yet."
                )
            return

        live: UserProfile | None
        try:
            live = await self.bot.lc.fetch_profile(user.lc_username)
        except LeetCodeError:
            logger.warning("Could not fetch profile for %s", user.lc_username, exc_info=True)
            live = None

        embed = profile_embed(
            user,
            display_name=display_name_for(target),
            avatar_url=member_avatar(target),
            profile=live,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlink", description="Unlink your LeetCode account and delete data")
    async def unlink(self, interaction: discord.Interaction) -> None:
        user = await self.bot.db.get_user(interaction.user.id)
        if user is None:
            await send_error(interaction, "Nothing to unlink", "You have no linked account.")
            return
        hosted = await self.bot.db.list_hosted_cohorts(interaction.user.id)
        if hosted:
            names = ", ".join(f"**{cohort.name}**" for cohort in hosted[:5])
            await send_error(
                interaction,
                "You still host a cohort",
                f"Delete or transfer {names} with `/cohort` before unlinking.",
            )
            return

        view = ConfirmView(interaction.user.id, confirm_label="Unlink", danger=True)
        embed = error_embed(
            "⚠️ Unlink account?",
            f"This removes **{user.lc_username}**, your goal, roadmap progress and reminders.\n"
            "This cannot be undone.",
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if view.value is not True:
            await interaction.edit_original_response(
                embed=error_embed("Unlink cancelled", "Your data is untouched."), view=None
            )
            return
        await self.bot.db.unlink_user(interaction.user.id)
        await interaction.edit_original_response(
            embed=success_embed(
                "Account unlinked",
                "Your LeetGo data has been removed. "
                "You can link again anytime with `/set-username`.",
            ),
            view=None,
        )
        logger.info("Unlinked user %s", interaction.user.id)


async def setup(bot: LeetGo) -> None:
    """Register the profile cog."""
    await bot.add_cog(Profile(bot))
