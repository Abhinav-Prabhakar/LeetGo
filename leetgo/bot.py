"""The LeetGo Discord client."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from . import __version__
from .config import Settings
from .db import Database
from .embeds import error_embed, info_embed
from .errors import (
    InvalidUsernameError,
    LeetCodeError,
    RateLimitedError,
    ServiceUnavailableError,
    UsernameTakenError,
    UserNotFoundError,
    new_error_id,
)
from .health import HealthServer
from .interactions import respond, send_error
from .leaderboard import LeaderboardService
from .leetcode import LeetCodeClient

logger = logging.getLogger("LeetGo")

COGS = (
    "leetgo.cogs.profile",
    "leetgo.cogs.stats",
    "leetgo.cogs.cohorts",
    "leetgo.cogs.roadmap",
    "leetgo.cogs.goals",
    "leetgo.cogs.reminders",
    "leetgo.cogs.meta",
)


class LeetGo(commands.Bot):
    """LeetGo bot with dependency container and lifecycle management."""

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = False

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
        )
        self.settings = settings
        self.version = __version__
        self.db = Database(settings.database_path)
        self.lc = LeetCodeClient(
            cache_ttl=settings.leetcode_cache_ttl,
            timeout=settings.leetcode_timeout,
            retries=settings.leetcode_retries,
        )
        self.leaderboards = LeaderboardService(self.lc)
        self.health = HealthServer(self, settings.health_host, settings.health_port)
        self.started_at = datetime.now(UTC)
        self._closing = False
        self.tree.on_error = self.on_tree_error  # type: ignore[method-assign]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def setup_hook(self) -> None:
        await self.db.connect()
        for extension in COGS:
            await self.load_extension(extension)
            logger.debug("Loaded extension %s", extension)

        try:
            if self.settings.guild_id is not None:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Synced %s commands to guild %s", len(synced), guild.id)
            else:
                synced = await self.tree.sync()
                logger.info("Synced %s global commands", len(synced))
        except discord.HTTPException:
            logger.exception("Slash command sync failed; existing commands remain available")

        await self.health.start()

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (%s) • %s guilds • %s users",
            self.user,
            self.user.id if self.user else "?",
            len(self.guilds),
            sum(guild.member_count or 0 for guild in self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers • /help",
            )
        )

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        logger.info("Shutting down LeetGo")
        await self.health.stop()
        await self.lc.close()
        await self.db.close()
        await super().close()

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------
    async def on_tree_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Map expected failures to friendly messages; log everything else."""
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.CommandOnCooldown):
            await respond(
                interaction,
                embed=error_embed(
                    "Slow down ⏳",
                    f"Try again in **{error.retry_after:.1f}s**.",
                ),
                ephemeral=True,
            )
            return
        if isinstance(error, app_commands.MissingPermissions):
            await send_error(
                interaction, "Missing permissions", "You do not have permission to use this."
            )
            return
        if isinstance(error, app_commands.BotMissingPermissions):
            await send_error(
                interaction,
                "I need more permissions",
                "Please ask an admin to grant the missing permissions.",
            )
            return
        if isinstance(error, app_commands.NoPrivateMessage):
            await send_error(interaction, "Server only", "This command only works in a server.")
            return
        if isinstance(original, UserNotFoundError):
            await send_error(
                interaction,
                "LeetCode user not found",
                "Double-check the username with `/set-username`.",
            )
            return
        if isinstance(original, InvalidUsernameError):
            await send_error(interaction, "Invalid username", str(original))
            return
        if isinstance(original, UsernameTakenError):
            await send_error(interaction, "Username already linked", str(original))
            return
        if isinstance(original, RateLimitedError):
            await send_error(
                interaction,
                "LeetCode is rate limiting us",
                f"Please try again in about **{original.retry_after:.0f}s**.",
            )
            return
        if isinstance(original, ServiceUnavailableError):
            await send_error(
                interaction,
                "LeetCode is unavailable",
                "The API did not respond. Please try again in a minute.",
            )
            return
        if isinstance(original, LeetCodeError):
            await send_error(interaction, "LeetCode error", str(original))
            return
        if isinstance(original, discord.Forbidden):
            await send_error(
                interaction,
                "I'm missing permissions",
                "Check that I can manage channels and send messages.",
            )
            return

        error_id = new_error_id()
        logger.error(
            "Command %s failed [%s]",
            getattr(interaction.command, "qualified_name", "unknown"),
            error_id,
            exc_info=error,
            extra={
                "guild_id": interaction.guild_id,
                "user_id": interaction.user.id,
                "command": getattr(interaction.command, "qualified_name", None),
                "error_id": error_id,
            },
        )
        try:
            await send_error(
                interaction,
                "Something went wrong",
                f"Try again in a moment. Reference: `{error_id}`",
            )
        except discord.HTTPException:  # pragma: no cover - interaction expired
            logger.warning("Could not deliver error message for %s", error_id)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        logger.error("Unhandled error in event %s", event_method, exc_info=True)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    async def on_guild_join(self, guild: discord.Guild) -> None:
        logger.info("Joined guild %s (%s)", guild.name, guild.id)
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            return
        embed = info_embed(
            "👋 Thanks for adding LeetGo!",
            "Track LeetCode progress, form study cohorts, and keep a daily streak alive.",
        )
        embed.add_field(
            name="Get started",
            value=(
                "1. `/set-username` — link LeetCode\n"
                "2. `/roadmap` — pick a path\n"
                "3. `/goal set` — commit to a target\n"
                "4. `/cohort create` — study together\n"
                "5. `/reminder set` — never miss a day"
            ),
            inline=False,
        )
        embed.add_field(
            name="Permissions",
            value="Manage Channels (cohorts), Embed Links, Send Messages, Read History.",
            inline=False,
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.debug("Could not send welcome message in guild %s", guild.id)
