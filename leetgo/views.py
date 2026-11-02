"""Shared interactive views."""

from __future__ import annotations

import discord


class ConfirmView(discord.ui.View):
    """A two-button confirmation prompt owned by one user."""

    def __init__(
        self,
        author_id: int,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        danger: bool = True,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None
        self.confirm_button.label = confirm_label
        self.cancel_button.label = cancel_label
        self.confirm_button.style = (
            discord.ButtonStyle.danger if danger else discord.ButtonStyle.success
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This confirmation is not for you.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self, interaction: discord.Interaction, _: discord.ui.Button[ConfirmView]
    ) -> None:
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, _: discord.ui.Button[ConfirmView]
    ) -> None:
        self.value = False
        self.stop()
        await interaction.response.defer()


class LinkView(discord.ui.View):
    """A single URL button."""

    def __init__(self, url: str, label: str = "Open link") -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
