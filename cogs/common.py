"""Shared plumbing for every ! command cog.

Blacklist gate, per-user command cooldown, the token getter and the
`run_attack` wrapper every simple command uses.
"""

import json
import os
import time

import discord
from discord.ext import commands

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1-minute cooldown between commands (per user)
COMMAND_COOLDOWN = 60
NO_COOLDOWN_USERS = {1503070818739949628}

# your own blacklist - list of user id strings; missing file = nobody
# blacklisted
BLACKLIST_FILE = os.path.join(HERE, "blacklist.json")


def is_blacklisted(user_id: int) -> bool:
    try:
        with open(BLACKLIST_FILE, encoding="utf-8") as f:
            return str(user_id) in json.load(f)
    except (OSError, ValueError):
        return False


async def blacklist_check(ctx) -> bool:
    """Global check - blocks every ! command for blacklisted users."""
    if is_blacklisted(ctx.author.id):
        try:
            await ctx.send(embed=discord.Embed(
                title="You are permanently banned from using our bot",
                description=("if you think we made a mistake pls explain it "
                             "on tickets."),
                color=0xED4245))
        except Exception:
            pass
        return False
    return True


def token() -> str:
    """The bot token from .env (DISCORD_TOKEN=...)."""
    return os.environ["DISCORD_TOKEN"]


def check_cooldown(user_id: int) -> float | None:
    """Return remaining seconds if the user is on command cooldown."""
    if user_id in NO_COOLDOWN_USERS:
        return None
    now = time.time()
    last = _command_cooldowns.get(user_id, 0)
    remaining = COMMAND_COOLDOWN - (now - last)
    if remaining > 0:
        return remaining
    _command_cooldowns[user_id] = now
    return None


# per-user command cooldown: user_id -> last command time
_command_cooldowns: dict[int, float] = {}


async def run_attack(ctx: commands.Context, label: str, coro_factory):
    """Cooldown check + run a command against ctx.guild.

    `coro_factory` receives the guild and returns the attack coroutine
    to await - one file per command, all sharing this wrapper.
    """
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
    await ctx.send(embed=discord.Embed(
        description=f"Running **{label}**...",
        color=0x5865F2))
    try:
        await coro_factory(ctx.guild)
        await ctx.send(embed=discord.Embed(
            title="Done",
            description=f"**{label}** finished successfully.",
            color=0x57F287))
    except Exception as exc:
        await ctx.send(embed=discord.Embed(
            title="Failed",
            description=f"**{label}** could not complete:\n`{str(exc)[:400]}`",
            color=0xED4245))
