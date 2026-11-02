"""Learning roadmaps with per-topic progress."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import ROADMAPS, SUCCESS_COLOR, Roadmap
from ..db import Database
from ..embeds import base_embed, info_embed
from ..formatting import format_percent, progress_bar, truncate
from ..interactions import require_linked_user, send_error

if TYPE_CHECKING:
    from ..bot import LeetGo

logger = logging.getLogger("LeetGo.roadmap")


def roadmap_embed(roadmap: Roadmap, completed: set[str]) -> discord.Embed:
    """Build the roadmap progress card."""
    done = len([topic for topic in roadmap.topics if topic in completed])
    total = len(roadmap.topics)
    percent = done / total * 100 if total else 0
    embed = base_embed(
        title=f"{roadmap.emoji} {roadmap.key} roadmap",
        description=roadmap.description,
        color=SUCCESS_COLOR if done == total else 0xFFA116,
    )
    embed.add_field(
        name="Progress",
        value=f"{progress_bar(percent)} **{format_percent(percent)}** • {done}/{total} topics",
        inline=False,
    )
    embed.add_field(
        name="Topics",
        value="\n".join(
            f"{'✅' if topic in completed else '⬜'} {truncate(topic, 90)}"
            for topic in roadmap.topics
        ),
        inline=False,
    )
    embed.set_footer(text="Tap a topic button to mark it complete or incomplete.")
    return embed


class RoadmapProgressView(discord.ui.View):
    """Toggle buttons persisted to the database."""

    def __init__(
        self,
        author_id: int,
        roadmap: Roadmap,
        completed: set[str],
        db: Database,
    ) -> None:
        super().__init__(timeout=300)
        self.author_id = author_id
        self.roadmap = roadmap
        self.completed = completed
        self.db = db
        self._buttons: dict[str, discord.ui.Button[RoadmapProgressView]] = {}
        for index, topic in enumerate(roadmap.topics):
            done = topic in completed
            button: discord.ui.Button[RoadmapProgressView] = discord.ui.Button(
                label=truncate(topic, 80),
                style=discord.ButtonStyle.success if done else discord.ButtonStyle.secondary,
                emoji="✅" if done else "⬜",
                custom_id=f"roadmap:{index}",
                row=index // 3,
            )
            button.callback = self._make_callback(topic)  # type: ignore[method-assign, assignment]
            self._buttons[topic] = button
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This roadmap belongs to someone else. Run `/roadmap` yourself.",
                ephemeral=True,
            )
            return False
        return True

    def _make_callback(self, topic: str) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def callback(interaction: discord.Interaction) -> None:
            if topic in self.completed:
                self.completed.discard(topic)
            else:
                self.completed.add(topic)
            await self.db.set_roadmap_progress(self.author_id, sorted(self.completed))
            button = self._buttons[topic]
            done = topic in self.completed
            button.style = discord.ButtonStyle.success if done else discord.ButtonStyle.secondary
            button.emoji = "✅" if done else "⬜"
            await interaction.response.edit_message(
                embed=roadmap_embed(self.roadmap, self.completed), view=self
            )

        return callback


class RoadmapSelectView(discord.ui.View):
    """Dropdown used to pick or change a roadmap."""

    def __init__(
        self,
        author_id: int,
        current: str | None,
        callback: Callable[[discord.Interaction, str], Awaitable[None]],
    ) -> None:
        super().__init__(timeout=180)
        self.author_id = author_id
        self._callback = callback
        options = [
            discord.SelectOption(
                label=f"{roadmap.emoji} {roadmap.key}",
                value=roadmap.key,
                description=truncate(roadmap.description, 100),
                default=roadmap.key == current,
            )
            for roadmap in ROADMAPS.values()
        ]
        select: discord.ui.Select[RoadmapSelectView] = discord.ui.Select(
            placeholder="Choose your learning path…", options=options
        )
        select.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This menu is not for you. Run `/roadmap` yourself.", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        select = self.children[0]
        assert isinstance(select, discord.ui.Select)
        await self._callback(interaction, select.values[0])


class RoadmapCog(commands.Cog):
    """Roadmap commands."""

    def __init__(self, bot: LeetGo) -> None:
        self.bot = bot

    @app_commands.command(name="roadmap", description="Choose or review your learning roadmap")
    async def roadmap(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        embed = base_embed(
            title="🗺️ Choose your learning path",
            description=(
                "Four curated paths, from fundamentals to interview sprint. "
                "Changing paths resets topic progress."
            ),
        )
        if user.roadmap and user.roadmap in ROADMAPS:
            current = ROADMAPS[user.roadmap]
            done = len([topic for topic in current.topics if topic in user.roadmap_progress])
            embed.add_field(
                name="Current path",
                value=(
                    f"{current.emoji} **{current.key}** • "
                    f"{done}/{len(current.topics)} topics complete"
                ),
                inline=False,
            )
        view = RoadmapSelectView(interaction.user.id, user.roadmap, self._select)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _select(self, interaction: discord.Interaction, key: str) -> None:
        roadmap = ROADMAPS[key]
        user = await self.bot.db.get_user(interaction.user.id)
        if user is None:
            await send_error(interaction, "No account linked", "Run `/set-username` first.")
            return
        if user.roadmap == key:
            embed = info_embed(
                f"{roadmap.emoji} {roadmap.key} is already active",
                "Your topic progress is unchanged. Use `/roadmap progress` to update it.",
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return
        await self.bot.db.set_roadmap(interaction.user.id, key, [])
        embed = base_embed(
            title=f"{roadmap.emoji} {roadmap.key} selected",
            description=roadmap.description,
            color=SUCCESS_COLOR,
        )
        embed.add_field(
            name="Topics to cover",
            value="\n".join(f"• {topic}" for topic in roadmap.topics),
            inline=False,
        )
        embed.set_footer(text="Use /roadmap progress to tick topics off.")
        await interaction.response.edit_message(embed=embed, view=None)
        logger.info("User %s selected roadmap %s", interaction.user.id, key)

    @app_commands.command(
        name="roadmap-progress", description="Tick topics off your current roadmap"
    )
    async def roadmap_progress(self, interaction: discord.Interaction) -> None:
        user = await require_linked_user(interaction, self.bot.db)
        if user is None:
            return
        roadmap = ROADMAPS.get(user.roadmap or "")
        if roadmap is None:
            await send_error(
                interaction,
                "No roadmap selected",
                "Run `/roadmap` first, then come back to track topics.",
            )
            return
        completed = set(user.roadmap_progress)
        view = RoadmapProgressView(interaction.user.id, roadmap, completed, self.bot.db)
        await interaction.response.send_message(
            embed=roadmap_embed(roadmap, completed), view=view, ephemeral=True
        )


async def setup(bot: LeetGo) -> None:
    """Register the roadmap cog."""
    await bot.add_cog(RoadmapCog(bot))
