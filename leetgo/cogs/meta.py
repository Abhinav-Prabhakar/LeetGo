"""Help, health and about commands."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import base_embed, error_embed, success_embed
from ..formatting import humanize_duration

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.meta")

GITHUB_URL = "https://github.com/Abhinav-Prabhakar/LeetGo"
# View Channels, Send Messages, Embed Links, Read Message History, Manage Channels.
INVITE_PERMISSIONS = 85_008


class HelpView(discord.ui.View):
    """Links shown under the help card."""

    def __init__(self, invite_url: str | None) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="GitHub", url=GITHUB_URL, style=discord.ButtonStyle.link, emoji="⭐"
            )
        )
        if invite_url:
            self.add_item(
                discord.ui.Button(
                    label="Add to server",
                    url=invite_url,
                    style=discord.ButtonStyle.link,
                    emoji="➕",
                )
            )


class Meta(commands.Cog):
    """Utility commands."""

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show everything LeetGo can do")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            title="🧭 LeetGo command guide",
            description=(
                "A Discord bot for the LeetCode grind: stats, cohorts, roadmaps, "
                "goals and timezone-aware reminders."
            ),
        )
        embed.add_field(
            name="👤 Profile",
            value=(
                "`/set-username` link LeetCode\n`/profile` account card\n`/unlink` delete your data"
            ),
            inline=True,
        )
        embed.add_field(
            name="📊 Stats",
            value=(
                "`/stats` full stats card\n"
                "`/daily` today's challenge\n"
                "`/compare` head-to-head\n"
                "`/leaderboard` cohort or server"
            ),
            inline=True,
        )
        embed.add_field(
            name="📚 Cohorts",
            value=(
                "`/cohort create` start a group\n"
                "`/cohort join` pick a group\n"
                "`/cohort leave` exit\n"
                "`/cohort info` roster & host\n"
                "`/cohort leaderboard` rankings\n"
                "`/cohort transfer` hand over host"
            ),
            inline=True,
        )
        embed.add_field(
            name="🗺️ Growth",
            value=(
                "`/roadmap` choose a path\n"
                "`/roadmap-progress` tick topics\n"
                "`/goal set` commit to a target\n"
                "`/goal view` pace check\n"
                "`/goal clear` remove goal"
            ),
            inline=True,
        )
        embed.add_field(
            name="⏰ Reminders",
            value=(
                "`/reminder set` daily DM\n"
                "`/reminder view` schedule\n"
                "`/reminder test` verify DMs\n"
                "`/reminder remove` stop"
            ),
            inline=True,
        )
        embed.add_field(
            name="🧰 Utility",
            value="`/help` this card\n`/ping` latency\n`/about` bot info",
            inline=True,
        )
        embed.set_footer(text="All commands are slash commands • LeetGo v" + self.bot.version)
        invite = self._invite_url()
        await interaction.response.send_message(embed=embed, view=HelpView(invite), ephemeral=True)

    @app_commands.command(name="ping", description="Check bot, database and API latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        start = time.perf_counter()
        db_ok = await self.bot.db.health_check()
        db_ms = (time.perf_counter() - start) * 1000
        uptime = humanize_duration(datetime.now(UTC) - self.bot.started_at)
        embed = (
            success_embed("🏓 Pong", "Everything looks healthy.")
            if db_ok
            else error_embed("🏓 Pong", "Database health check failed.")
        )
        embed.add_field(name="Gateway", value=f"{self.bot.latency * 1000:.0f} ms", inline=True)
        embed.add_field(name="Database", value=f"{db_ms:.1f} ms", inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        users = await self.bot.db.count_users()
        embed.add_field(name="Users", value=f"{users:,}", inline=True)
        embed.add_field(
            name="Cache TTL", value=f"{self.bot.settings.leetcode_cache_ttl}s", inline=True
        )
        await interaction.edit_original_response(embed=embed)

    @app_commands.command(name="about", description="About LeetGo, links and live stats")
    async def about(self, interaction: discord.Interaction) -> None:
        users = await self.bot.db.count_users()
        cohorts = await self.bot.db.count_cohorts()
        reminders = await self.bot.db.count_active_reminders()
        uptime = humanize_duration(datetime.now(UTC) - self.bot.started_at)
        embed = base_embed(
            title="⚡ LeetGo",
            description=(
                "**Grind smarter, together.**\n"
                "An open-source Discord bot that turns LeetCode practice into a shared habit."
            ),
            url=GITHUB_URL,
        )
        embed.add_field(name="Version", value=self.bot.version, inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Linked users", value=f"{users:,}", inline=True)
        embed.add_field(name="Cohorts", value=f"{cohorts:,}", inline=True)
        embed.add_field(name="Reminders", value=f"{reminders:,}", inline=True)
        embed.add_field(
            name="Stack",
            value="Python 3.11+ • discord.py • aiohttp • SQLite (WAL) • Docker",
            inline=False,
        )
        embed.set_footer(text="MIT licensed • Built with discord.py")
        await interaction.response.send_message(embed=embed, view=HelpView(self._invite_url()))

    def _invite_url(self) -> str | None:
        if self.bot.user is None:
            return None
        return (
            "https://discord.com/oauth2/authorize"
            f"?client_id={self.bot.user.id}"
            f"&permissions={INVITE_PERMISSIONS}"
            "&scope=bot%20applications.commands"
        )


async def setup(bot: LeetGo) -> None:
    """Register the meta cog."""
    await bot.add_cog(Meta(bot))
