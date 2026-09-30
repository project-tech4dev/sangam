"""Whether the importer may read a URL. Every research tool asks this first."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.ingest.adapters._http import HEADERS, USER_AGENT
from app.ingest.sources import rule_for_host

logger = logging.getLogger(__name__)

_ROBOTS: dict[str, RobotFileParser | None] = {}




async def check_url(url: str) -> str | None:
    """None when the importer may read this URL, else the reason it may not."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"{url} is not an http(s) URL."
    host = parsed.hostname or ""

    # Two separate questions. The registry says whether this site may be read at
    # all; robots.txt says which paths. Being a permitted source is not a pass
    # for every URL on it - indiacsr.in is crawl_allowed and still bars /wp-admin/.
    # rule_for_host, not the first match: several products share a host
    # (mcacdm.nic.in has four), and the strictest of them decides.
    found = rule_for_host(host)
    source = found[1] if found else None
    if source is not None and not source.dispatchable:
        return (
            f"{source.name} ({source.host}) is registered as {source.access_rule.value} and must "
            f"not be read automatically. {source.basis} Report this to the user; do not look for "
            f"another route to the same content."
        )

    allowed = await _robots_allows(parsed.scheme, host, url)
    if allowed and source is None:
        # Readable, but nobody has classified it. Record it so the list grows
        # from what we actually read, rather than from guesswork.
        await _note_proposal(host, url, robots_result="allowed")
    if allowed is None:
        if source is not None:
            # A person checked this host and recorded the basis, so an
            # unreadable robots.txt today does not overrule that decision.
            return None
        return (
            f"{host} did not serve a readable robots.txt, so whether it permits automated reading "
            f"is unknown. An unknown rule is not permission: leave it, and tell the user it needs "
            f"a check before Sangam reads it."
        )
    if not allowed:
        return f"{host} disallows this path in its robots.txt for our crawler."
    return None


async def _robots_allows(scheme: str, host: str, url: str) -> bool | None:
    """True/False from robots.txt; None when the file could not be read at all."""
    if host not in _ROBOTS:
        _ROBOTS[host] = await _load_robots(scheme, host)
    parser = _ROBOTS[host]
    if parser is None:
        return None
    if not parser.entries and parser.default_entry is None:
        return True  # served, but empty: nothing is disallowed
    return parser.can_fetch(USER_AGENT, url)


async def _load_robots(scheme: str, host: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get(f"{scheme}://{host}/robots.txt")
    except httpx.HTTPError as exc:
        logger.info("robots.txt for %s could not be fetched: %s", host, exc)
        return None
    # RFC 9309: 4xx means no restrictions; 5xx means treat everything as
    # disallowed. The inventory saw exactly that from the government portals,
    # which answer 503 outside India - unreadable is not permission.
    if response.status_code >= 500:
        return None
    if response.status_code >= 400:
        parser.parse([])
        return parser
    parser.parse(response.text.splitlines())
    return parser


async def _note_proposal(host: str, url: str, *, robots_result: str) -> None:
    """Best-effort: a proposal is a note, and failing to take it must never
    block a read or raise into the agent."""
    try:
        from app.db.pool import get_pool

        pool = get_pool()
        # Normalised the same way sources_on_host() matches, so promoting this
        # into the JSON with the bare host actually resolves the proposal.
        host = host.lower().removeprefix("www.")
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO ingest_source_proposals (host, first_seen_url, robots_result) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (host) DO UPDATE SET last_seen_at = now(), "
                "times_seen = ingest_source_proposals.times_seen + 1",
                (host, url, robots_result),
            )
    except Exception:
        logger.debug("could not record a source proposal for %s", host, exc_info=True)
