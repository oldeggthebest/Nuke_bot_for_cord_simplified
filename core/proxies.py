"""Proxy rotation - spread Discord API traffic across proxies.txt.

The fork's HTTPClient only supports a single static proxy (self.proxy),
which burns out the moment a nuke wave starts. This module:

  1. parses proxies.txt into a pool - accepts any of:
        ip:port
        user:pass@ip:port
        http://ip:port
        http://user:pass@ip:port
        socks5://host:port          (needs aiohttp-socks installed)
     blank lines and # comments are skipped
  2. wraps HTTPClient.request so every attempt - including every 429
     retry - leaves through a fresh proxy (retries never burn the same
     IP twice)
  3. wraps HTTPClient.ws_connect so each gateway reconnect gets the
     next proxy in the pool
  4. quarantines proxies that fail to connect, with exponential
     backoff before they're tried again

Note: Discord's token-level global rate limits survive proxy rotation
(the limit rides on the bot token, not the source IP), but IP-level
throttling, Cloudflare pressure and connection bans all spread out -
which is where the 289-second global waits were coming from.
"""

import asyncio
import json
import logging
import time

import aiohttp
import discord
from discord.http import HTTPClient

log = logging.getLogger("nbot.proxy")

_ORIGINAL_REQUEST = HTTPClient.request
_ORIGINAL_WS_CONNECT = HTTPClient.ws_connect

_MAX_RETRIES = 30          # hard ceiling per API call, same as patch429
_REQUEST_TIMEOUT = 8       # per-request total timeout via proxy (seconds)
_QUARANTINE_BASE = 10       # seconds before a dead proxy is retried
_QUARANTINE_CAP = 120


def parse_proxy_line(line):
    """One line of proxies.txt -> (proxy_url, aiohttp.BasicAuth or None)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # farm format: ip:port:user:pass
    if "@" not in line and "://" not in line and line.count(":") == 3:
        ip, port, user, pw = line.split(":")
        return f"http://{ip}:{port}", aiohttp.BasicAuth(user, pw)
    if "://" not in line:
        line = "http://" + line
    auth = None
    if "@" in line:
        scheme, rest = line.split("://", 1)
        creds, hostport = rest.rsplit("@", 1)
        if ":" in creds:
            user, pw = creds.split(":", 1)
            auth = aiohttp.BasicAuth(user, pw)
        line = f"{scheme}://{hostport}"
    return line, auth


def load_proxies(path):
    """Read and parse proxies.txt, skipping blanks and comments."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            parsed = parse_proxy_line(raw)
            if parsed is not None:
                out.append(parsed)
    return out


class ProxyPool:
    def __init__(self, entries):
        self._slots = [
            {"proxy": proxy, "auth": auth, "fails": 0, "retry_at": 0.0}
            for proxy, auth in entries
        ]
        self._idx = 0

    def __len__(self):
        return len(self._slots)

    def __bool__(self):
        return bool(self._slots)

    def _pick(self):
        """Round-robin over slots, skipping quarantined ones."""
        n = len(self._slots)
        now = time.monotonic()
        for _ in range(n):
            slot = self._slots[self._idx % n]
            self._idx += 1
            if slot["retry_at"] <= now:
                return slot
        # everything quarantined - take the one closest to coming back
        return min(self._slots, key=lambda s: s["retry_at"])

    def next(self):
        slot = self._pick()
        return slot["proxy"], slot["auth"], slot

    def mark_ok(self, slot):
        slot["fails"] = 0

    def mark_failed(self, slot):
        slot["fails"] += 1
        backoff = min(_QUARANTINE_BASE * (2 ** min(slot["fails"] - 1, 4)),
                      _QUARANTINE_CAP)
        slot["retry_at"] = time.monotonic() + backoff
        log.warning("proxy %s unreachable - quarantined for %.0fs (fail #%d)",
                    slot["proxy"], backoff, slot["fails"])


def _parse_retry_after(exc):
    try:
        return float(json.loads(exc.text).get("retry_after"))
    except Exception:
        return None


async def _request_rotating(self, route, *, files=None, form=None, **kwargs):
    """HTTPClient.request wrapper - fresh proxy per attempt + 429 retry."""
    saved_proxy, saved_auth = self.proxy, self.proxy_auth
    for attempt in range(_MAX_RETRIES):
        proxy, auth, slot = _POOL.next()
        self.proxy, self.proxy_auth = proxy, auth   # original reads these
        kwargs.setdefault("timeout", aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT))
        try:
            result = await _ORIGINAL_REQUEST(self, route, files=files,
                                             form=form, **kwargs)
            _POOL.mark_ok(slot)
            return result
        except discord.HTTPException as exc:
            if exc.status != 429:
                raise
            retry_after = _parse_retry_after(exc)
            if retry_after is None:
                raise                 # Cloudflare ban, not a Discord limit
            log.warning("429 on %s %s via %s - retrying in %.2fs (attempt %d/%d)",
                        route.method, route.url, proxy, retry_after,
                        attempt + 1, _MAX_RETRIES)
            await asyncio.sleep(retry_after)
        except (OSError, aiohttp.ClientHttpProxyError):
            # dead, unreachable, or auth-dead (407) proxy - quarantine
            # it and hop to the next instead of crashing the login
            _POOL.mark_failed(slot)
            await asyncio.sleep(0.5)
    raise RuntimeError("proxy pool gave up after too many retries")


async def _ws_connect_rotating(self, url, *, compress=0):
    last = None
    for _ in range(5):
        proxy, auth, slot = _POOL.next()
        self.proxy, self.proxy_auth = proxy, auth
        try:
            return await _ORIGINAL_WS_CONNECT(self, url, compress=compress)
        except (OSError, aiohttp.ClientHttpProxyError) as exc:
            last = exc
            _POOL.mark_failed(slot)
            await asyncio.sleep(0.5)
    raise last


_POOL = None


def install_proxy_rotation(pool):
    """Replace HTTPClient.request / ws_connect with rotating versions."""
    global _POOL
    _POOL = pool
    HTTPClient.request = _request_rotating
    HTTPClient.ws_connect = _ws_connect_rotating
    log.info("proxy rotation installed for %d proxies", len(pool))


def set_pool(pool):
    """Install the pool for ATTACK rotation only (proxy_pool()), WITHOUT
    patching the bot's gateway/HTTPClient - the gateway stays direct so it
    is fast and never touches the metered proxy data."""
    global _POOL
    _POOL = pool


def pool_active() -> bool:
    """True when a proxy pool is installed (rotation on)."""
    return _POOL is not None


def proxy_pool():
    """The installed pool, or None - lets raw callers (usergw, panel
    token checks) ride the same rotation instead of going direct into
    this network's MITM."""
    return _POOL


async def raw_request(session, method, url, *, headers=None, json=None,
                      retries=8, timeout=20, retry_cap=10.0):
    """Raw aiohttp request that rides the proxy pool when one is
    installed - direct otherwise. Built for REST engines (backup
    restore, backups fetch) that don't go through discord.py's
    HTTPClient, so they don't get mangled by this network's MITM on
    direct requests.

    Never raises. Returns (status, body_dict) - a non-dict body
    (Cloudflare HTML, text) comes back as ({}, status).
    """
    headers = headers or {}
    attempts = retries if _POOL is not None else min(retries, 3)
    for attempt in range(attempts):
        proxy = auth = slot = None
        if _POOL is not None:
            proxy, auth, slot = _POOL.next()
        req_timeout = _REQUEST_TIMEOUT if proxy else timeout
        try:
            async with session.request(
                method, url, headers=headers, json=json,
                proxy=proxy, proxy_auth=auth,
                timeout=aiohttp.ClientTimeout(total=req_timeout),
            ) as resp:
                body = await resp.json(content_type=None)
                if slot is not None:
                    _POOL.mark_ok(slot)
                if resp.status == 429 and isinstance(body, dict):
                    try:
                        wait = min(float(body.get("retry_after", 1)),
                                   retry_cap)
                    except (TypeError, ValueError):
                        wait = 1.0
                    await asyncio.sleep(wait + 0.4)
                    continue
                if not isinstance(body, dict):
                    return resp.status, {}
                return resp.status, body
        except Exception:
            if slot is not None:
                _POOL.mark_failed(slot)
            await asyncio.sleep(0.5)
    return 0, {}
