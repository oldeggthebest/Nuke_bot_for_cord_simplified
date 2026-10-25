"""!spamchannels - spam the raid message in every channel."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class SpamChannels(commands.Cog):
    """spam the raid message in every channel."""

    @commands.command(name="spamchannels")
    async def spamchannels(self, ctx: commands.Context):
        """spam the raid message in every channel."""
        await run_attack(
            ctx, "Spam Channels",
            lambda g: attacks.spam_channels(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(SpamChannels())
