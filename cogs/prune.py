"""!prune - prune inactive members (7 days)."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class Prune(commands.Cog):
    """prune inactive members (7 days)."""

    @commands.command(name="prune")
    async def prune(self, ctx: commands.Context):
        """prune inactive members (7 days)."""
        await run_attack(
            ctx, "Prune",
            lambda g: attacks.prune_members(token(), g.id, days=7))


async def setup(bot: commands.Bot):
    await bot.add_cog(Prune())
