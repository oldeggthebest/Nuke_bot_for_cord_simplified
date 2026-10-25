"""patch429 - fixes this fork's broken 429 handling.

The fork's HTTPClient.request only sleeps-and-retries a 429 when the
response carries a Cloudflare `Via` header AND a JSON body. Real Discord
429s that lack one of those fall through to a bare `raise
HTTPException(429)`, which kills every op in a burst. This wrapper
catches those leaked 429s, reads retry_after from the body, sleeps, and
retries - while still re-raising 429s with no retry_after (Cloudflare
bans), preserving the fork's original intent.
"""

import asyncio
import json
import logging

import discord
from discord.http import HTTPClient

log = logging.getLogger("nbot.429")

_ORIGINAL_REQUEST = HTTPClient.request
_MAX_RETRIES = 200


def _parse_retry_after(exc):
    try:
        return float(json.loads(exc.text).get("retry_after"))
    except Exception:
        return None


async def _request_with_429_retry(self, route, *, files=None, form=None, **kwargs):
    for attempt in range(_MAX_RETRIES):
        try:
            return await _ORIGINAL_REQUEST(self, route, files=files,
                                           form=form, **kwargs)
        except discord.HTTPException as exc:
            if exc.status != 429:
                raise
            retry_after = _parse_retry_after(exc)
            if retry_after is None:
                raise                 # Cloudflare ban, not a Discord limit
            log.warning("429 on %s %s - retrying in %.2fs (attempt %d/%d)",
                        route.method, route.url, retry_after,
                        attempt + 1, _MAX_RETRIES)
            await asyncio.sleep(retry_after)
    raise discord.HTTPException(None, "gave up after too many 429 retries")


def install_429_retry():
    HTTPClient.request = _request_with_429_retry
    log.info("429 retry wrapper installed")
