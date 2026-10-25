"""!nickall - rename every member."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class NickAll(commands.Cog):
    """rename every member."""

    @commands.command(name="nickall")
    async def nickall(self, ctx: commands.Context):
        """rename every member."""
        await run_attack(
            ctx, "Nick All",
            lambda g: attacks.nick_all(token(), g.id, "nuked"))


async def setup(bot: commands.Bot):
    await bot.add_cog(NickAll())
