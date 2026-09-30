"""One polite HTTP client for every adapter: identified, slow, one host at a time."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import defaultdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Sangam/0.1 (+https://github.com/project-tech4dev/sangam)"
# Explicit, and not httpx's default: its default Accept-Encoding advertises zstd,
# which India CSR's WAF answers with 403. The user agent stays honest.
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
TIMEOUT_SECONDS = 25

# One request in flight per host, and a pause after it. The source inventory's
# rule is "crawl slowly, identify the crawler"; this is where that is honoured.
_HOST_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
POLITE_DELAY_SECONDS = 1.0
RETRY_STATUS = (429, 503)
BACKOFF_SECONDS = (5.0, 15.0)


class SourceUnavailable(RuntimeError):
    """The source could not be read. Carries a sentence for the run summary."""


def content_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_json(url: str, params: dict[str, Any] | None = None, *, delay: float | None = None) -> Any:
    host = httpx.URL(url).host or url
    async with _HOST_LOCKS[host]:
        try:
            data = await _get_with_backoff(url, params, host)
        finally:
            await asyncio.sleep(POLITE_DELAY_SECONDS if delay is None else delay)
    return data


async def _get_with_backoff(url: str, params: dict[str, Any] | None, host: str) -> Any:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=TIMEOUT_SECONDS, headers=HEADERS
    ) as client:
        for attempt, pause in enumerate((*BACKOFF_SECONDS, None)):
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise SourceUnavailable(f"{host} could not be reached: {exc}") from exc
            if response.status_code in RETRY_STATUS and pause is not None:
                logger.info("%s returned %s, backing off %ss", host, response.status_code, pause)
                await asyncio.sleep(pause)
                continue
            if response.status_code in RETRY_STATUS:
                raise SourceUnavailable(
                    f"{host} is rate-limiting this client (HTTP {response.status_code}) and did not "
                    f"recover after {attempt} retries. Nothing was read; try again later."
                )
            if response.is_error:
                raise SourceUnavailable(f"{host} returned HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise SourceUnavailable(f"{host} returned a non-JSON body") from exc
    raise SourceUnavailable(f"{host} could not be read")
