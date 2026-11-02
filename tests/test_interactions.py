"""Interaction plumbing and shared view tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import discord

from leetgo.db import Database
from leetgo.embeds import error_embed
from leetgo.interactions import (
    display_name_for,
    member_avatar,
    require_guild,
    require_linked_user,
    respond,
    send_error,
)
from leetgo.views import ConfirmView, LinkView


class FakeResponse:
    def __init__(self, *, done: bool = False) -> None:
        self._done = done
        self.messages: list[dict[str, Any]] = []
        self.deferred = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, *args: Any, **kwargs: Any) -> None:
        self.messages.append({"args": args, **kwargs})

    async def defer(self) -> None:
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


class FakeInteraction:
    def __init__(self, user_id: int = 1, *, done: bool = False) -> None:
        self.user = SimpleNamespace(
            id=user_id,
            name="Alice",
            display_name="Alice",
            display_avatar=SimpleNamespace(url="https://example.com/a.png"),
        )
        self.guild = object()
        self.response = FakeResponse(done=done)
        self.followup = FakeFollowup()


async def test_respond_uses_initial_response() -> None:
    interaction = FakeInteraction()
    embed = error_embed("Oops", "Try again")
    await respond(interaction, embed=embed, ephemeral=True)
    assert interaction.response.messages[0]["embed"] is embed
    assert interaction.response.messages[0]["ephemeral"] is True
    assert interaction.followup.messages == []


async def test_respond_uses_followup_when_acknowledged() -> None:
    interaction = FakeInteraction(done=True)
    await respond(interaction, content="hello")
    assert interaction.response.messages == []
    assert interaction.followup.messages[0]["content"] == "hello"


async def test_send_error_is_ephemeral() -> None:
    interaction = FakeInteraction()
    await send_error(interaction, "No account", "Run /set-username")
    message = interaction.response.messages[0]
    assert message["ephemeral"] is True
    assert message["embed"].title == "No account"


async def test_require_linked_user(db: Database) -> None:
    await db.link_user(1, "alice", "alice_lc")
    interaction = FakeInteraction(1)

    found = await require_linked_user(interaction, db)
    assert found is not None and found.lc_username == "alice_lc"
    assert interaction.response.messages == []

    missing = await require_linked_user(interaction, db, user_id=2)
    assert missing is None
    assert interaction.response.messages[0]["embed"].title == "That member is not linked"

    self_missing = await require_linked_user(interaction, db, user_id=3)
    assert self_missing is None


async def test_require_linked_user_targets_other_member(db: Database) -> None:
    await db.link_user(2, "bob", "bob_lc")
    interaction = FakeInteraction(1)
    found = await require_linked_user(interaction, db, user_id=2)
    assert found is not None and found.lc_username == "bob_lc"


def test_require_guild() -> None:
    interaction = FakeInteraction()
    assert require_guild(interaction) is interaction.guild  # type: ignore[arg-type]
    interaction.guild = None
    assert require_guild(interaction) is None


def test_display_name_and_avatar() -> None:
    user = FakeInteraction().user
    assert display_name_for(user) == "Alice"
    assert member_avatar(user) == "https://example.com/a.png"
    user.display_name = None
    assert display_name_for(user) == "Alice"
    user.display_avatar = None
    assert member_avatar(user) is None


async def test_confirm_view_ownership_and_confirmation() -> None:
    view = ConfirmView(1, confirm_label="Delete", cancel_label="Keep", danger=True)
    assert view.confirm_button.label == "Delete"
    assert view.cancel_button.label == "Keep"
    assert view.confirm_button.style == discord.ButtonStyle.danger

    owner = FakeInteraction(1)
    assert await view.interaction_check(owner) is True
    await view.confirm_button.callback(owner)
    assert view.value is True
    assert view.is_finished()
    assert owner.response.deferred is True

    other_view = ConfirmView(1)
    other = FakeInteraction(2)
    assert await other_view.interaction_check(other) is False
    assert other.response.messages[0]["ephemeral"] is True
    other_view.stop()


async def test_confirm_view_cancel_and_success_style() -> None:
    view = ConfirmView(7, danger=False)
    assert view.confirm_button.style == discord.ButtonStyle.success
    interaction = FakeInteraction(7)
    await view.cancel_button.callback(interaction)
    assert view.value is False
    assert view.is_finished()
    assert interaction.response.deferred is True


def test_link_view() -> None:
    view = LinkView("https://example.com", label="Docs")
    assert view.timeout is None
    assert len(view.children) == 1
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    assert button.label == "Docs"
    assert button.url == "https://example.com"
    assert button.style == discord.ButtonStyle.link
