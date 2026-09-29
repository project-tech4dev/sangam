"""GDELT DOC 2.0: a free public API, so the rows come back already structured."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from app.ingest.adapters._http import SourceUnavailable, get_json
from app.ingest.records import NewsMentionRecord

API = "https://api.gdeltproject.org/api/v2/doc/doc"
# The query the seed CSVs were built from, kept identical so a re-run extends
# the same corpus rather than starting a second one.
DEFAULT_QUERY = '(CSR OR "corporate social responsibility" OR grant) AND (foundation OR trust) sourcecountry:india'


async def fetch(query: str = DEFAULT_QUERY, limit: int = 25) -> list[NewsMentionRecord]:
    data = await get_json(
        API,
        {"query": query, "mode": "ArtList", "maxrecords": min(limit, 250), "format": "json",
         "timespan": "3months"},
    )
    if not isinstance(data, dict) or "articles" not in data:
        # An empty body is not an empty result. GDELT answers a throttled or
        # malformed query with no 'articles' key at all, and reporting that as
        # "0 records" would be a false zero.
        raise SourceUnavailable(
            "GDELT returned no article list for this query - it was throttled or the query "
            "was rejected. This is not the same as 'no articles matched'."
        )
    now = datetime.now(UTC)
    records = []
    for art in data["articles"]:
        url = art.get("url")
        if not url:
            continue
        records.append(
            NewsMentionRecord(
                url=url,
                title=art.get("title") or None,
                seendate=_parse_seendate(art.get("seendate")),
                domain=art.get("domain") or urlparse(url).netloc,
                topic="funders_grants",
                source_url=url,
                source_name="gdelt",
                fetched_at=now,
                as_of=now.date().isoformat(),
            )
        )
    return records


def _parse_seendate(raw: str | None) -> datetime | None:
    # GDELT stamps are '20260921T104500Z'.
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if raw else None
    except ValueError:
        return None
