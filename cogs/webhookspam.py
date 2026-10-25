"""!webhookspam - webhook-spam every channel."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class WebhookSpam(commands.Cog):
    """webhook-spam every channel."""

    @commands.command(name="webhookspam")
    async def webhookspam(self, ctx: commands.Context):
        """webhook-spam every channel."""
        await run_attack(
            ctx, "Webhook Spam",
            lambda g: attacks.webhook_spam(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(WebhookSpam())
