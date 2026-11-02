"""Interaction helpers shared by every cog."""

from __future__ import annotations

from typing import Any

import discord

from .db import Database
from .embeds import error_embed
from .models import UserRecord


async def respond(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed | None = None,
    content: str | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> Any:
    """Respond to an interaction whether or not it has already been deferred."""
    kwargs: dict[str, Any] = {
        "embed": embed,
        "content": content,
        "view": view,
        "ephemeral": ephemeral,
    }
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)
    return await interaction.response.send_message(**kwargs)


async def send_error(
    interaction: discord.Interaction,
    title: str,
    description: str | None = None,
) -> None:
    """Send a consistent ephemeral error embed."""
    await respond(interaction, embed=error_embed(title, description), ephemeral=True)


async def get_linked_user(db: Database, user_id: int) -> UserRecord | None:
    """Fetch a linked account, if any."""
    return await db.get_user(user_id)


async def require_linked_user(
    interaction: discord.Interaction,
    db: Database,
    *,
    user_id: int | None = None,
) -> UserRecord | None:
    """Return the target user's record or send a friendly linking prompt."""
    target_id = user_id if user_id is not None else interaction.user.id
    user = await db.get_user(target_id)
    if user is None:
        if target_id == interaction.user.id:
            await send_error(
                interaction,
                "No LeetCode account linked",
                "Use `/set-username` first, then try again.",
            )
        else:
            await send_error(
                interaction,
                "That member is not linked",
                "Ask them to run `/set-username` first.",
            )
        return None
    return user


def require_guild(interaction: discord.Interaction) -> discord.Guild | None:
    """Return the guild for a guild-only command."""
    if interaction.guild is None:
        return None
    return interaction.guild


def display_name_for(user: discord.abc.User) -> str:
    """Return a member's display name, falling back to the global name."""
    return getattr(user, "display_name", None) or user.name


def member_avatar(user: discord.abc.User) -> str | None:
    """Return the user's avatar URL, if available."""
    return user.display_avatar.url if user.display_avatar else None
