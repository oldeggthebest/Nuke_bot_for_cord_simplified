"""!mentionall - ping everyone with @everyone."""

import discord
from discord.ext import commands

from core import attacks
from .common import run_attack, token


class MentionAll(commands.Cog):
    """ping everyone with @everyone."""

    @commands.command(name="mentionall")
    async def mentionall(self, ctx: commands.Context):
        """ping everyone with @everyone."""
        await run_attack(
            ctx, "Mention All",
            lambda g: attacks.mention_all(token(), g.id))


async def setup(bot: commands.Bot):
    await bot.add_cog(MentionAll())
