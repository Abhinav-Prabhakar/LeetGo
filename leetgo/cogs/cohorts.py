"""Study cohorts backed by Discord channels."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import COHORT_NAME_MAX_LENGTH
from ..embeds import (
    cohort_embed,
    info_embed,
    leaderboard_embed,
    success_embed,
    warning_embed,
)
from ..formatting import sanitize_channel_name, truncate
from ..interactions import display_name_for, require_linked_user, send_error
from ..models import Cohort
from ..views import ConfirmView

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.cohorts")


async def cohort_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest cohorts in the current guild."""
    if interaction.guild_id is None:
        return []
    bot = cast("LeetGo", interaction.client)
    cohorts = await bot.db.list_cohorts(interaction.guild_id)
    query = current.lower()
    return [
        app_commands.Choice(name=truncate(cohort.name, 100), value=cohort.name)
        for cohort in cohorts
        if query in cohort.name.lower()
    ][:25]


class CohortJoinView(discord.ui.View):
    """Dropdown used when `/cohort join` is called without a name."""

    def __init__(
        self,
        author_id: int,
        cohorts: list[Cohort],
        callback: Callable[[discord.Interaction, Cohort], Awaitable[None]],
    ) -> None:
        super().__init__(timeout=180)
        self.author_id = author_id
        self._cohorts = {cohort.cohort_id: cohort for cohort in cohorts}
        self._callback = callback
        select: discord.ui.Select[CohortJoinView] = discord.ui.Select(
            placeholder="Choose a cohort to join…",
            options=[
                discord.SelectOption(
                    label=truncate(cohort.name, 100),
                    value=str(cohort.cohort_id),
                    description="Study together and climb the leaderboard",
                )
                for cohort in cohorts[:25]
            ],
        )
        select.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        select = self.children[0]
        assert isinstance(select, discord.ui.Select)
        cohort = self._cohorts[int(select.values[0])]
        await self._callback(interaction, cohort)


class Cohorts(commands.Cog):
    """Create, join and manage study cohorts."""

    cohort = app_commands.Group(
        name="cohort",
        description="Create and manage study cohorts",
        guild_only=True,
    )

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _resolve_cohort(
        self, interaction: discord.Interaction, name: str | None
    ) -> Cohort | None:
        assert interaction.guild_id is not None
        if name:
            cohort = await self.bot.db.get_cohort_by_name(interaction.guild_id, name)
            if cohort is None:
                await send_error(
                    interaction,
                    "Cohort not found",
                    f"No cohort named **{truncate(name, 80)}** in this server.",
                )
                return None
        else:
            user = await self.bot.db.get_user(interaction.user.id)
            if user is None or user.cohort_id is None:
                await send_error(
                    interaction,
                    "You're not in a cohort",
                    "Join one with `/cohort join`, or pass a cohort name.",
                )
                return None
            cohort = await self.bot.db.get_cohort(user.cohort_id)
            if cohort is None:
                await send_error(interaction, "Cohort missing", "It may have been deleted.")
                return None

        if cohort.guild_id is not None and cohort.guild_id != interaction.guild_id:
            await send_error(interaction, "Wrong server", "That cohort belongs elsewhere.")
            return None
        return cohort

    async def _ensure_manage_channels(self, interaction: discord.Interaction) -> bool:
        assert interaction.guild is not None
        me = interaction.guild.me
        if me is None or not me.guild_permissions.manage_channels:
            await send_error(
                interaction,
                "I need Manage Channels",
                "Ask an admin to grant **Manage Channels** so I can create cohort channels.",
            )
            return False
        return True

    async def _host_name(self, guild: discord.Guild, cohort: Cohort) -> str:
        if cohort.host_id is None:
            return "Unknown"
        member = guild.get_member(cohort.host_id)
        if member is not None:
            return display_name_for(member)
        try:
            user = await self.bot.fetch_user(cohort.host_id)
            return display_name_for(user)
        except discord.HTTPException:
            return "Unknown"

    async def _delete_cohort(self, cohort: Cohort, guild: discord.Guild) -> None:
        if cohort.channel_id is not None:
            channel = guild.get_channel(cohort.channel_id)
            if channel is not None:
                try:
                    await channel.delete(reason=f"LeetGo cohort deleted: {cohort.name}")
                except discord.HTTPException:
                    logger.warning("Could not delete cohort channel %s", cohort.channel_id)
        await self.bot.db.delete_cohort(cohort.cohort_id)
        self.bot.leaderboards.invalidate()
        logger.info("Deleted cohort %s", cohort.name)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @cohort.command(name="create", description="Create a cohort with its own text channel")
    @app_commands.describe(name="Cohort name (a channel is created from it)")
    async def create(self, interaction: discord.Interaction, name: str) -> None:
        assert interaction.guild is not None
        assert interaction.guild_id is not None
        name = name.strip()
        if not name or len(name) > COHORT_NAME_MAX_LENGTH:
            await send_error(
                interaction,
                "Invalid name",
                f"Use a name between 1 and {COHORT_NAME_MAX_LENGTH} characters.",
            )
            return
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if user.cohort_id is not None:
            await send_error(
                interaction,
                "You're already in a cohort",
                "Leave it with `/cohort leave` before creating another.",
            )
            return
        if await self.bot.db.get_cohort_by_name(interaction.guild_id, name):
            await send_error(interaction, "Name already used", "Pick a different cohort name.")
            return
        existing = await self.bot.db.list_cohorts(interaction.guild_id)
        if len(existing) >= self.bot.settings.max_cohorts_per_guild:
            await send_error(
                interaction,
                "Cohort limit reached",
                f"This server has reached {self.bot.settings.max_cohorts_per_guild} cohorts.",
            )
            return
        if not await self._ensure_manage_channels(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        category = discord.utils.get(
            interaction.guild.categories, name=self.bot.settings.cohort_category
        )
        try:
            if category is None:
                category = await interaction.guild.create_category(
                    self.bot.settings.cohort_category,
                    reason="LeetGo cohort category setup",
                )
        except discord.Forbidden:
            await send_error(
                interaction,
                "Cannot create category",
                "Grant **Manage Channels**, or create a category named "
                f"**{self.bot.settings.cohort_category}** manually.",
            )
            return

        slug = sanitize_channel_name(name)
        if discord.utils.get(interaction.guild.text_channels, name=slug):
            await send_error(
                interaction,
                "Channel already exists",
                f"A channel named **#{slug}** already exists. Pick another cohort name.",
            )
            return

        try:
            channel = await interaction.guild.create_text_channel(
                slug,
                category=category,
                topic=truncate(
                    f"LeetGo study cohort • hosted by {display_name_for(interaction.user)} "
                    "• /cohort leaderboard",
                    1024,
                ),
                reason=f"LeetGo cohort created by {interaction.user}",
            )
        except discord.HTTPException:
            logger.exception("Failed to create cohort channel")
            await send_error(
                interaction,
                "Could not create the channel",
                "Check my permissions and the category channel limit, then try again.",
            )
            return

        try:
            cohort = await self.bot.db.create_cohort(
                name, interaction.guild.id, channel.id, interaction.user.id
            )
        except Exception:
            try:
                await channel.delete(reason="LeetGo cohort creation rollback")
            except discord.HTTPException:
                logger.warning("Rollback failed for channel %s", channel.id)
            raise

        welcome = info_embed(
            f"🎉 Welcome to {cohort.name}!",
            f"Hosted by {interaction.user.mention}. This is your shared study room.",
        )
        welcome.add_field(
            name="How to join",
            value="Others can run `/cohort join` and pick this cohort.",
            inline=False,
        )
        welcome.add_field(
            name="Stay accountable",
            value="Use `/cohort leaderboard` and `/reminder set` to keep the group moving.",
            inline=False,
        )
        try:
            await channel.send(embed=welcome)
        except discord.HTTPException:
            logger.warning("Could not send welcome message to %s", channel.id)

        self.bot.leaderboards.invalidate()
        embed = success_embed(
            "✅ Cohort created",
            f"**{cohort.name}** is live in {channel.mention}. Others can join with `/cohort join`.",
        )
        await interaction.edit_original_response(embed=embed)
        logger.info("Created cohort %s in guild %s", cohort.name, interaction.guild_id)

    @cohort.command(name="join", description="Join a study cohort")
    @app_commands.describe(name="Cohort name (leave empty to pick from a menu)")
    @app_commands.autocomplete(name=cohort_name_autocomplete)
    async def join(self, interaction: discord.Interaction, name: str | None = None) -> None:
        assert interaction.guild is not None
        assert interaction.guild_id is not None
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if user.cohort_id is not None:
            await send_error(
                interaction,
                "Already in a cohort",
                "Use `/cohort leave` first if you want to switch.",
            )
            return
        cohorts = await self.bot.db.list_cohorts(interaction.guild_id)
        if not cohorts:
            await send_error(
                interaction,
                "No cohorts yet",
                "Create the first one with `/cohort create`.",
            )
            return

        if name:
            cohort = await self.bot.db.get_cohort_by_name(interaction.guild_id, name)
            if cohort is None:
                await send_error(interaction, "Cohort not found", f"No cohort named **{name}**.")
                return
            await interaction.response.defer(ephemeral=True)
            await self._join(interaction, cohort, component=False)
            return

        embed = info_embed(
            "📚 Pick a cohort",
            "Choose a study group from the dropdown. You can leave anytime.",
        )
        embed.add_field(name="Available", value=str(len(cohorts)), inline=True)

        async def on_join(interaction: discord.Interaction, cohort: Cohort) -> None:
            await self._join(interaction, cohort, component=True)

        view = CohortJoinView(interaction.user.id, cohorts, on_join)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _join(
        self, interaction: discord.Interaction, cohort: Cohort, *, component: bool
    ) -> None:
        user = await self.bot.db.get_user(interaction.user.id)
        if user is None:
            await send_error(interaction, "No account linked", "Run `/set-username` first.")
            return
        if user.cohort_id is not None:
            await send_error(interaction, "Already in a cohort", "Leave it before joining another.")
            return
        await self.bot.db.set_user_cohort(interaction.user.id, cohort.cohort_id)
        self.bot.leaderboards.invalidate()
        channel = f"<#{cohort.channel_id}>" if cohort.channel_id else "the cohort channel"
        embed = success_embed(
            "✅ Joined cohort",
            f"You're now part of **{cohort.name}**. Say hi in {channel}!",
        )
        if component:
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.edit_original_response(embed=embed)
        logger.info("User %s joined cohort %s", interaction.user.id, cohort.name)

    @cohort.command(name="leave", description="Leave your current cohort")
    async def leave(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        user = await self.bot.db.get_user(interaction.user.id)
        if user is None or user.cohort_id is None:
            await send_error(interaction, "Not in a cohort", "Nothing to leave.")
            return
        cohort = await self.bot.db.get_cohort(user.cohort_id)
        if cohort is None:
            await self.bot.db.clear_user_cohort(interaction.user.id)
            await send_error(interaction, "Cohort missing", "Your membership has been cleaned up.")
            return

        if cohort.host_id == interaction.user.id:
            members = await self.bot.db.list_cohort_members(cohort.cohort_id)
            others = [member for member in members if member.user_id != interaction.user.id]
            if others:
                await send_error(
                    interaction,
                    "You're the host",
                    "Transfer ownership with `/cohort transfer`, "
                    "or delete it with `/cohort delete`.",
                )
                return
            view = ConfirmView(interaction.user.id, confirm_label="Delete cohort", danger=True)
            await interaction.response.send_message(
                embed=warning_embed(
                    "Delete this cohort?",
                    f"**{cohort.name}** is empty. Leaving will delete the cohort and its channel.",
                ),
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if view.value is not True:
                await interaction.edit_original_response(
                    embed=info_embed("Cancelled", "Your cohort is still here."), view=None
                )
                return
            await self._delete_cohort(cohort, interaction.guild)
            await interaction.edit_original_response(
                embed=success_embed("Cohort deleted", "The channel and cohort data were removed."),
                view=None,
            )
            return

        await self.bot.db.clear_user_cohort(interaction.user.id)
        self.bot.leaderboards.invalidate()
        await interaction.response.send_message(
            embed=success_embed("👋 Left cohort", f"You left **{cohort.name}**."),
            ephemeral=True,
        )
        logger.info("User %s left cohort %s", interaction.user.id, cohort.name)

    @cohort.command(name="info", description="Show details for a cohort")
    @app_commands.describe(name="Cohort name (defaults to yours)")
    @app_commands.autocomplete(name=cohort_name_autocomplete)
    async def info(self, interaction: discord.Interaction, name: str | None = None) -> None:
        assert interaction.guild is not None
        cohort = await self._resolve_cohort(interaction, name)
        if cohort is None:
            return
        members = await self.bot.db.list_cohort_members(cohort.cohort_id)
        host_name = await self._host_name(interaction.guild, cohort)
        channel = f"<#{cohort.channel_id}>" if cohort.channel_id else None
        embed = cohort_embed(
            cohort,
            host_name=host_name,
            member_count=len(members),
            channel_mention=channel,
        )
        if members:
            roster = "\n".join(
                f"• <@{member.user_id}> — **{member.lc_username}**" for member in members[:15]
            )
            embed.add_field(name="Roster", value=roster, inline=False)
        await interaction.response.send_message(embed=embed)

    @cohort.command(name="list", description="List every cohort in this server")
    async def list_cohorts(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        cohorts = await self.bot.db.list_cohorts(interaction.guild_id)
        if not cohorts:
            await send_error(interaction, "No cohorts yet", "Start one with `/cohort create`.")
            return
        embed = info_embed(
            f"📚 Cohorts in {interaction.guild.name}",
            f"{len(cohorts)} study groups • join with `/cohort join`",
        )
        for cohort in cohorts[:20]:
            count = await self.bot.db.count_cohort_members(cohort.cohort_id)
            channel = f"<#{cohort.channel_id}>" if cohort.channel_id else "no channel"
            embed.add_field(
                name=truncate(cohort.name, 100),
                value=f"{count} members • {channel}",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    @cohort.command(name="leaderboard", description="Rank a cohort by problems solved")
    @app_commands.describe(name="Cohort name (defaults to yours)")
    @app_commands.autocomplete(name=cohort_name_autocomplete)
    async def leaderboard(self, interaction: discord.Interaction, name: str | None = None) -> None:
        assert interaction.guild is not None
        cohort = await self._resolve_cohort(interaction, name)
        if cohort is None:
            return
        members = await self.bot.db.list_cohort_members(cohort.cohort_id)
        if not members:
            await send_error(interaction, "Empty cohort", "Invite people with `/cohort join`.")
            return
        await interaction.response.defer()
        entries = await self.bot.leaderboards.fetch(
            members[: self.bot.settings.max_leaderboard_users]
        )
        await interaction.followup.send(
            embed=leaderboard_embed(
                entries[:10],
                title=f"🏆 {cohort.name} leaderboard",
                subtitle=f"{len(members)} members • updated every 5 minutes",
            )
        )

    @cohort.command(name="delete", description="Delete a cohort you host")
    @app_commands.describe(name="Cohort name (defaults to yours)")
    @app_commands.autocomplete(name=cohort_name_autocomplete)
    async def delete(self, interaction: discord.Interaction, name: str | None = None) -> None:
        assert interaction.guild is not None
        cohort = await self._resolve_cohort(interaction, name)
        if cohort is None:
            return
        if cohort.host_id != interaction.user.id:
            await send_error(interaction, "Host only", "Only the cohort host can delete it.")
            return
        view = ConfirmView(interaction.user.id, confirm_label="Delete", danger=True)
        await interaction.response.send_message(
            embed=warning_embed(
                "Delete cohort?",
                f"This deletes **{cohort.name}**, its channel, and every membership.",
            ),
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.value is not True:
            await interaction.edit_original_response(
                embed=info_embed("Cancelled", "Nothing was deleted."), view=None
            )
            return
        await self._delete_cohort(cohort, interaction.guild)
        await interaction.edit_original_response(
            embed=success_embed("Cohort deleted", f"**{cohort.name}** is gone."), view=None
        )

    @cohort.command(name="transfer", description="Transfer cohort ownership to another member")
    @app_commands.describe(member="New host", name="Cohort name (defaults to yours)")
    @app_commands.autocomplete(name=cohort_name_autocomplete)
    async def transfer(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str | None = None,
    ) -> None:
        assert interaction.guild is not None
        cohort = await self._resolve_cohort(interaction, name)
        if cohort is None:
            return
        if cohort.host_id != interaction.user.id:
            await send_error(interaction, "Host only", "Only the host can transfer ownership.")
            return
        if member.id == interaction.user.id:
            await send_error(interaction, "Pick someone else", "You already own this cohort.")
            return
        target = await self.bot.db.get_user(member.id)
        if target is None or target.cohort_id != cohort.cohort_id:
            await send_error(
                interaction,
                "Not a member",
                "That person must be linked and in this cohort first.",
            )
            return
        await self.bot.db.set_cohort_host(cohort.cohort_id, member.id)
        await interaction.response.send_message(
            embed=success_embed(
                "Ownership transferred",
                f"{member.mention} is now the host of **{cohort.name}**.",
            )
        )
        logger.info("Cohort %s transferred to %s", cohort.cohort_id, member.id)

    # ------------------------------------------------------------------
    # Cleanup listeners
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.TextChannel):
            return
        cohort = await self.bot.db.get_cohort_by_channel(channel.id)
        if cohort is not None:
            await self.bot.db.delete_cohort(cohort.cohort_id)
            self.bot.leaderboards.invalidate()
            logger.info("Cohort %s removed after its channel was deleted", cohort.name)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        user = await self.bot.db.get_user(member.id)
        if user is None or user.cohort_id is None:
            return
        cohort = await self.bot.db.get_cohort(user.cohort_id)
        if cohort is None or (cohort.guild_id is not None and cohort.guild_id != member.guild.id):
            return
        if cohort.host_id == member.id:
            members = await self.bot.db.list_cohort_members(cohort.cohort_id)
            others = [
                candidate
                for candidate in members
                if candidate.user_id is not None and candidate.user_id != member.id
            ]
            if others:
                await self.bot.db.set_cohort_host(cohort.cohort_id, others[0].user_id or 0)
                await self.bot.db.clear_user_cohort(member.id)
                logger.info(
                    "Cohort %s host left; transferred to %s", cohort.name, others[0].user_id
                )
            else:
                await self._delete_cohort(cohort, member.guild)
        else:
            await self.bot.db.clear_user_cohort(member.id)
        self.bot.leaderboards.invalidate()


async def setup(bot: LeetGo) -> None:
    """Register the cohorts cog."""
    await bot.add_cog(Cohorts(bot))
