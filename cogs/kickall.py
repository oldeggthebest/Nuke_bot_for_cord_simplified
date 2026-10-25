"""!kickall - kick every member in the server."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class KickAll(commands.Cog):
    """kick every member in the server."""

    @commands.command(name="kickall")
    async def kickall(self, ctx: commands.Context):
        """kick every member in the server."""
        await run_attack(
            ctx, "Kick All",
            lambda g: attacks.kick_all(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(KickAll())
