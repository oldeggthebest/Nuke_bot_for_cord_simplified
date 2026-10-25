"""!createchannels - create 50 new channels."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class CreateChannels(commands.Cog):
    """create 50 new channels."""

    @commands.command(name="createchannels")
    async def createchannels(self, ctx: commands.Context):
        """create 50 new channels."""
        await run_attack(
            ctx, "Create Channels",
            lambda g: attacks.create_channels(token(), g.id, "nuked", 50))


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateChannels())
