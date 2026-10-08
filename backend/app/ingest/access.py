"""Whether the importer may read a URL. Every research tool asks this first."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.egress import guarded_client, private_address_refusal
from app.ingest.adapters._http import HEADERS, USER_AGENT
from app.ingest.sources import AccessRule, rule_for_url

logger = logging.getLogger(__name__)

_ROBOTS: dict[str, RobotFileParser | None] = {}


def canonical_url(url: str) -> str:
    """The URL exactly as httpx will send it (IDNA host, dot segments resolved): what is checked is what is fetched."""
    return str(httpx.URL(url))


async def check_url(url: str) -> str | None:
    """None when the importer may read this URL, else the reason it may not. Never raises."""
    try:
        return await _check_url(canonical_url(url))
    except Exception as exc:  # noqa: BLE001 - a URL that cannot be checked is not read
        return f"{url} could not be checked ({type(exc).__name__}: {exc}), so it is not read."


async def _check_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"{url} is not an http(s) URL."
    host = parsed.hostname or ""
    if parsed.username is not None or parsed.password is not None:
        return f"{url} carries a user name or password, so it is not read: the host is not what it seems."
    private = await private_address_refusal(url)
    if private:
        return private

    # Two separate questions. The registry says whether this site may be read at
    # all; robots.txt says which paths. Being a permitted source is not a pass
    # for every URL on it - indiacsr.in is crawl_allowed and still bars /wp-admin/.
    # rule_for_url: the host's strictest rule, except on a path a path-scoped entry claims.
    found = rule_for_url(url)
    source = found[1] if found else None
    if source is not None and source.path_scoped:
        why = source.path_refusal(url)
        if why:
            return (
                f"{source.name} ({source.host}) is registered as {source.access_rule.value}, and {why}. "
                f"{source.basis} Report this; do not look for another route to the same content."
            )
    elif source is not None and not source.dispatchable:
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
        if source is not None and not source.path_scoped:
            # A person checked this host and recorded the basis, so an
            # unreadable robots.txt today does not overrule that decision.
            return None
        if source is not None:
            return (
                f"{host} did not serve a readable robots.txt today, and {source.name} is read only on paths "
                f"robots.txt leaves open, so it is not read now. Tell the user; do not look for another route."
            )
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
        async with guarded_client(timeout=15, headers=HEADERS) as client:
            response = await client.get(f"{scheme}://{host}/robots.txt")
    except Exception as exc:  # noqa: BLE001 - unreadable is None, never a crash
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


def source_banner(url: str) -> str:
    """The line a fetch tool puts above a page whose source decides how its values are labelled."""
    found = rule_for_url(url)
    if found is None:
        return ""
    rule, source = found
    if rule is AccessRule.MANUAL_AGGREGATOR:
        return (
            f"[{source.name} is an aggregator. Every value below is claimed: save it with source_type "
            f"'aggregator' and evidence_tier 'claimed', as a lead or a corroboration, never in place of "
            f"the organisation's own document.]\n\n"
        )
    if rule is AccessRule.INTERNAL_RESEARCH:
        return (
            f"[{source.name}: the team's earlier research, pinned to one commit. Every value below is "
            f"claimed: save it with source_type 'prior_research' and evidence_tier 'claimed', citing this "
            f"URL, then re-read the links it cites under their own access rules.]\n\n"
        )
    return ""
