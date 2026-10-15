"""Candidate pages for a funder's calls: what Import already cited, its website, and one search of its own domain."""

from __future__ import annotations

from urllib.parse import urlparse

from langchain_tavily import TavilySearch

# Pages Import read for this funder, from its documents and the facts that cite them.
_CITED = """
SELECT DISTINCT d.source_url AS url, coalesce(d.title, '') AS title
FROM documents d
WHERE d.source_url ~ '^https?://' AND d.source_url !~* '\\.pdf($|\\?)'
  AND (d.funder_id = %(id)s
       OR EXISTS (SELECT 1 FROM document_links dl WHERE dl.document_id = d.id AND dl.funder_id = %(id)s))
LIMIT 20
"""


def host_of(url: str | None) -> str | None:
    host = urlparse(url or "").hostname
    return host.removeprefix("www.") if host else None


async def candidates(conn, funder: dict, *, api_key: str) -> tuple[list[tuple[str, str]], str | None]:
    """(pages, why the search found nothing when it failed rather than came back empty)."""
    found: dict[str, str] = {}
    if funder["website"]:
        found[funder["website"]] = "the funder's home page"
    for r in await (await conn.execute(_CITED, {"id": funder["id"]})).fetchall():
        found.setdefault(r["url"], r["title"])
    host, failed = host_of(funder["website"]), None
    if host and not api_key:
        failed = "no TAVILY_API_KEY, so its site was not searched"
    if host and api_key:
        # Only the funder's own domain: an aggregator's copy of a call is not the funder's word.
        search = TavilySearch(max_results=5, tavily_api_key=api_key, include_domains=[host])
        try:
            raw = await search.ainvoke({"query": f"{funder['name']} call for proposals grant apply NGO"})
            if isinstance(raw, dict) and raw.get("error"):
                # Tavily reports quota and auth failures in the payload, not as an exception.
                failed = f"the search of its site failed ({raw['error']})"
            for r in (raw.get("results", []) if isinstance(raw, dict) else []):
                if isinstance(r, dict) and r.get("url"):
                    found.setdefault(r["url"], r.get("title") or "")
        except Exception as exc:  # noqa: BLE001 - a failed search leaves the other candidates
            failed = f"the search of its site failed ({type(exc).__name__}: {exc})"
    own = {host_of(funder["website"])} if funder["website"] else set()
    return [(u, t) for u, t in found.items() if not own or host_of(u) in own], failed
