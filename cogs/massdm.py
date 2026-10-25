"""!massdm - DM every member in the server."""

import asyncio

import discord
from discord.ext import commands

from core import attacks
from .common import check_cooldown, token


class MassDM(commands.Cog):
    """Sends the same DM to every member it can reach."""

    @commands.command(name="massdm")
    async def massdm(self, ctx: commands.Context, *, message: str = None):
        """Mass DM every member - asks for the message if not given."""
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

        if not message:
            await ctx.send(embed=discord.Embed(
                title="Mass DM",
                description="**What should be DMed?** Type the message in this "
                            "channel. You have **60 seconds**.",
                color=0x5865F2))

            def check(m: discord.Message):
                return (m.author.id == ctx.author.id
                        and m.channel.id == ctx.channel.id)

            try:
                msg = await ctx.bot.wait_for("message", check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send(embed=discord.Embed(
                    description="Timed out - no message received. Run "
                                "`!massdm` to try again.",
                    color=0xFEE75C))
                return
            message = msg.content

        await ctx.send(embed=discord.Embed(
            description="Running **Mass DM**...",
            color=0x5865F2))
        try:
            await attacks.mass_dm(token(), ctx.guild.id, message)
            await ctx.send(embed=discord.Embed(
                title="Done",
                description="**Mass DM** finished successfully.",
                color=0x57F287))
        except Exception as exc:
            await ctx.send(embed=discord.Embed(
                title="Failed",
                description=f"**Mass DM** could not complete:\n"
                            f"`{str(exc)[:400]}`",
                color=0xED4245))


async def setup(bot: commands.Bot):
    await bot.add_cog(MassDM())
