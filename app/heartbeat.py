"""Check-ins with an outside monitor (e.g. healthchecks.io).

The app checks in every minute while the bot is talking to Telegram. If the check-ins stop,
for whatever reason (NAS off, home internet down, container stopped, bot stuck), the
monitor alerts you. Nothing on the NAS can raise that alarm when the NAS itself is offline.
"""

import logging

import httpx

log = logging.getLogger(__name__)


def ping(url: str) -> None:
    if not url:
        return
    try:
        httpx.get(url, timeout=10).raise_for_status()
    except httpx.HTTPError as e:
        # Don't log the URL: anyone with it can send check-ins.
        log.warning("Heartbeat check-in failed: %s", type(e).__name__)
