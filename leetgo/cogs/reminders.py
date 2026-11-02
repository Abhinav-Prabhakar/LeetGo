"""Timezone-aware daily reminders delivered by DM."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..embeds import base_embed, error_embed, info_embed, success_embed
from ..errors import LeetCodeError
from ..formatting import discord_timestamp
from ..interactions import require_linked_user, send_error
from ..leetcode import DailyChallenge
from ..timezones import (
    is_due,
    local_now,
    next_occurrence,
    search_timezones,
    validate_timezone,
)
from ..views import LinkView

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.reminders")


async def timezone_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest IANA timezones."""
    return [app_commands.Choice(name=zone, value=zone) for zone in search_timezones(current)]


class Reminders(commands.Cog):
    """Daily reminder commands and scheduler."""

    reminder = app_commands.Group(name="reminder", description="Daily study reminders")

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot
        self._loop = tasks.loop(seconds=bot.settings.reminder_poll_seconds)(self._tick)
        self._loop.before_loop(self._before_loop)
        self._last_cleanup: str | None = None

    async def cog_load(self) -> None:
        self._loop.start()

    async def cog_unload(self) -> None:
        self._loop.cancel()

    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @reminder.command(name="set", description="Set a daily DM reminder")
    @app_commands.describe(
        hour="Hour in your timezone (0-23)",
        minute="Minute (0-59)",
        timezone="IANA timezone, e.g. Asia/Kolkata (defaults to your saved zone)",
    )
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def set_reminder(
        self,
        interaction: discord.Interaction,
        hour: app_commands.Range[int, 0, 23],
        minute: app_commands.Range[int, 0, 59],
        timezone: str | None = None,
    ) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        zone = timezone or user.timezone
        try:
            validate_timezone(zone)
        except ValueError as exc:
            await send_error(interaction, "Invalid timezone", str(exc))
            return
        await self.bot.db.set_reminder(interaction.user.id, hour, minute, zone)
        nxt = next_occurrence(hour, minute, zone)
        embed = success_embed(
            "⏰ Reminder set",
            f"Daily study reminder at **{hour:02d}:{minute:02d}** ({zone}).",
        )
        embed.add_field(
            name="Next reminder",
            value=f"{discord_timestamp(nxt, 'f')} ({discord_timestamp(nxt, 'R')})",
            inline=False,
        )
        embed.add_field(
            name="Make sure DMs are open",
            value="Server members must allow direct messages from this bot.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("User %s set reminder %02d:%02d %s", interaction.user.id, hour, minute, zone)

    @reminder.command(name="view", description="Show your reminder schedule")
    async def view_reminder(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if not user.has_reminder:
            await send_error(
                interaction, "No reminder set", "Create one with `/reminder set hour:20 minute:0`."
            )
            return
        assert user.reminder_hour is not None and user.reminder_minute is not None
        local = local_now(user.timezone)
        nxt = next_occurrence(user.reminder_hour, user.reminder_minute, user.timezone)
        embed = info_embed(
            "⏰ Your reminder",
            f"Daily at **{user.reminder_hour:02d}:{user.reminder_minute:02d}** "
            f"in **{user.timezone}**.",
        )
        embed.add_field(name="Your local time", value=local.strftime("%H:%M"), inline=True)
        embed.add_field(name="Next", value=discord_timestamp(nxt, "R"), inline=True)
        embed.add_field(name="Timezone", value=user.timezone, inline=True)
        embed.set_footer(text="Change it with /reminder set • remove it with /reminder remove")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminder.command(name="remove", description="Stop daily reminders")
    async def remove_reminder(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        if not user.has_reminder:
            await send_error(interaction, "No reminder set", "There is nothing to remove.")
            return
        await self.bot.db.clear_reminder(interaction.user.id)
        await interaction.response.send_message(
            embed=success_embed("🔕 Reminders off", "You will not receive daily DMs anymore."),
            ephemeral=True,
        )
        logger.info("User %s removed their reminder", interaction.user.id)

    @reminder.command(name="test", description="Send a test reminder to your DMs")
    async def test_reminder(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = base_embed(
            title="⏰ Test reminder",
            description="This is what your daily nudge will look like. You're all set!",
        )
        embed.add_field(
            name="Keep the streak alive",
            value="Use `/daily`, `/stats`, and `/goal view` to stay on track.",
            inline=False,
        )
        try:
            await interaction.user.send(embed=embed)
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=error_embed(
                    "Could not send a DM",
                    "Open **Privacy & Safety → Direct Messages** for this server and try again.",
                )
            )
            return
        await interaction.edit_original_response(
            embed=success_embed("Test sent", "Check your direct messages.")
        )

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    async def _tick(self) -> None:
        now = datetime.now(UTC)
        today = now.date().isoformat()
        if self._last_cleanup != today:
            try:
                removed = await self.bot.db.cleanup_reminder_log(days=30)
                if removed:
                    logger.info("Pruned %s old reminder log rows", removed)
            except Exception:  # pragma: no cover - maintenance best effort
                logger.exception("Reminder log cleanup failed")
            self._last_cleanup = today

        users = await self.bot.db.list_reminder_users()
        if not users:
            return
        daily: DailyChallenge | None = None
        daily_attempted = False

        for user in users:
            if user.user_id is None or not user.has_reminder:
                continue
            assert user.reminder_hour is not None and user.reminder_minute is not None
            try:
                due, date_key = is_due(user.reminder_hour, user.reminder_minute, user.timezone, now)
            except ValueError:
                logger.warning("Invalid timezone %r for user %s", user.timezone, user.user_id)
                continue
            if not due:
                continue
            if await self.bot.db.was_reminder_sent(user.user_id, date_key):
                continue

            if not daily_attempted:
                daily_attempted = True
                try:
                    daily = await self.bot.lc.fetch_daily()
                except LeetCodeError:
                    logger.warning("Daily challenge unavailable for reminders", exc_info=True)

            target = self.bot.get_user(user.user_id)
            if target is None:
                try:
                    target = await self.bot.fetch_user(user.user_id)
                except discord.HTTPException:
                    logger.warning("Could not resolve reminder user %s", user.user_id)
                    continue

            embed = base_embed(
                title="⏰ Daily coding reminder",
                description=f"Time to solve something, **{user.lc_username}**. "
                "Small sessions compound.",
            )
            view: LinkView | None = None
            if daily is not None:
                embed.add_field(
                    name=f"{daily.difficulty} daily challenge",
                    value=f"[{daily.title}]({daily.url})\nAcceptance {daily.ac_rate:.0f}%",
                    inline=False,
                )
                view = LinkView(daily.url, "Solve today's challenge")
            embed.add_field(
                name="Quick actions",
                value="`/daily` • `/stats` • `/goal view` • `/cohort leaderboard`",
                inline=False,
            )
            embed.set_footer(text="Use /reminder remove to stop these DMs")
            try:
                if view is not None:
                    await target.send(embed=embed, view=view)
                else:
                    await target.send(embed=embed)
            except discord.Forbidden:
                logger.info("DMs closed for user %s; marking reminder handled", user.user_id)
                await self.bot.db.mark_reminder_sent(user.user_id, date_key)
            except discord.HTTPException:
                logger.warning("Failed to DM user %s", user.user_id, exc_info=True)
            else:
                await self.bot.db.mark_reminder_sent(user.user_id, date_key)
                logger.info("Sent reminder to %s", user.user_id)


async def setup(bot: LeetGo) -> None:
    """Register the reminders cog."""
    await bot.add_cog(Reminders(bot))
