"""Stories for Media & Signals and the Registry's "In the news" (spec section 5): filtered, keyset-paged, counted.

Runs as the caller: RLS decides which stories and entity links a reader sees (0044)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from app.ingest.news.bars import level
from app.ingest.news.feeds import STATES as NORTH_EAST
from app.repositories import keyset
from app.repositories.public_sql import PUBLIC_STORY, STORY_CHANNEL, is_private_url, public_url

SOCIAL = ["LinkedIn", "Instagram", "X", "YouTube"]
WEB = ["other web", "organisation site"]
COUNT_CAP = 501  # a card shows "500+" past this
_SOURCE = ("CASE WHEN ml.source_type = ANY(%(social)s) THEN 'social' "
           "WHEN ml.source_type = ANY(%(web)s) THEN 'web' ELSE 'news' END")
_PUB = "coalesce(s.published_on, s.first_seen_at::date)"
_FILTER_TEMPLATE = f"""
  AND (%(topic)s::text IS NULL OR s.topic = %(topic)s)
  AND (%(sentiment)s::text IS NULL OR {{sentiment}} = %(sentiment)s)
  AND (%(source)s::text IS NULL OR {_SOURCE} = %(source)s)
  AND (%(since)s::date IS NULL OR {_PUB} >= %(since)s)
  AND (%(q)s::text IS NULL OR s.search @@ websearch_to_tsquery('simple', %(q)s))"""
# D8 "my area": the caller's organisations' states, North East civil society, national policy news.
_MY_STATES = """(SELECT CASE WHEN l.kind = 'state' THEN l.id ELSE l.parent_id END FROM org_locations ol
  JOIN locations l ON l.id = ol.location_id WHERE ol.org_id IN (SELECT app.my_org_ids()))"""
_MINE = f"""CASE
  WHEN st.id IN {_MY_STATES} THEN st.name
  WHEN s.feed IN ('fcra', 'ngo_north_east') AND (s.scope = 'north_east' OR st.name = ANY(%(ne)s))
    THEN concat_ws(' · ', st.name, 'North East civil society')
  WHEN s.scope = 'national' AND s.content_kind = 'news' AND s.topic IN ('fcra', 'governance', 'csr_funding')
    THEN 'National policy' END"""
_AREA = f"""
  AND (%(area)s = 'all' OR (%(area)s = 'mine' AND ({_MINE}) IS NOT NULL)
       OR (%(area)s = 'north_east' AND (s.scope = 'north_east' OR st.name = ANY(%(ne)s))))"""


# A profile reads the same signed in or out: only what clears the public bar.
_PROFILE = f"\n                 AND {PUBLIC_STORY}"
_MY_ORGS = "\n                 AND (%(staff)s OR x.id IN (SELECT app.my_org_ids()))"


def _filters(bucket: str) -> str:
    """The shared filters; in the org and funder buckets sentiment is that organisation's own stance (e.stance)."""
    if bucket == "general":
        return _FILTER_TEMPLATE.replace("{sentiment}", "s.sentiment") + _AREA
    return _FILTER_TEMPLATE.replace("{sentiment}", "e.stance")


_COLS = f"""s.id, s.headline, s.headline_generated, s.summary, s.published_on, s.date_source, s.content_kind,
  s.is_news, s.scope, s.topic, s.sentiment, s.main_host, {public_url("ml.url")} AS main_url, ml.source_type,
  {STORY_CHANNEL} AS channel, {_PUB} AS pub"""


@dataclass(frozen=True)
class Filters:
    bucket: Literal["org", "funder", "general"] = "general"
    org: str | None = None
    funder: str | None = None
    topic: str | None = None
    sentiment: str | None = None
    source: Literal["news", "social", "web"] | None = None
    since: Literal["30d", "all"] = "all"
    q: str | None = None
    area: Literal["mine", "north_east", "all"] = "all"
    staff: bool = False  # staff see every organisation; background and hidden stories reach no one


def _base(bucket: str, *, profile: bool = False) -> str:
    """One row per entity link in the org and funder buckets, one per topic story in general.
    A profile shows any organisation's public stories; the list's org bucket only the caller's, unless staff."""
    if bucket == "general":
        return f"""SELECT {_COLS}, s.id AS row_id, s.visibility, coalesce(s.topic_match, 0)::float8 AS m,
                     coalesce(s.topic_confidence, 0)::float8 AS c, coalesce({_MINE}, st.name) AS area_reason,
                     NULL::bigint AS e_org, NULL::bigint AS e_funder
                   FROM news_stories s LEFT JOIN news_links ml ON ml.id = s.main_link_id
                   LEFT JOIN LATERAL (
                     SELECT l.id, l.name FROM news_story_locations n JOIN locations l ON l.id = n.location_id
                     WHERE n.story_id = s.id AND l.kind = 'state'
                     ORDER BY l.id IN {_MY_STATES} DESC, l.name = ANY(%(ne)s) DESC, l.name LIMIT 1) st ON true
                   WHERE s.feed IS NOT NULL AND s.visibility = 'listed' AND s.is_news"""
    side, table, param = ("org_id", "orgs", "org") if bucket == "org" else ("funder_id", "funders", "funder")
    return f"""SELECT {_COLS}, e.id AS row_id, e.visibility, e.match::float8 AS m, e.confidence::float8 AS c,
                 e.org_id AS e_org, e.funder_id AS e_funder
               FROM news_story_entities e JOIN news_stories s ON s.id = e.story_id
               JOIN {table} x ON x.id = e.{side}
               LEFT JOIN news_links ml ON ml.id = s.main_link_id
               WHERE (%({param})s::text IS NULL OR x.slug = %({param})s)
                 AND e.visibility <> 'hidden' AND s.is_news{_PROFILE if profile else _MY_ORGS if side == "org_id" else ""}"""


def _params(f: Filters, today: date) -> dict[str, Any]:
    return {"org": f.org, "funder": f.funder, "topic": f.topic, "sentiment": f.sentiment, "source": f.source,
            "since": today - timedelta(days=30) if f.since == "30d" else None, "q": f.q or None,
            "social": SOCIAL, "web": WEB, "staff": f.staff, "area": f.area, "ne": list(NORTH_EAST)}


_KEY_TYPES = {"m": float, "c": float, "pub": date.fromisoformat, "row_id": int}


def _typed(values: tuple, keys: list[str]) -> tuple:
    """A cursor of the wrong shape or types is a bad cursor (400), never a database error (500)."""
    if len(values) != len(keys):
        raise ValueError("bad cursor")
    try:
        return tuple(_KEY_TYPES[k](v) for k, v in zip(keys, values, strict=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("bad cursor") from exc


async def _page(pool, sql: str, params: dict, keys: list[str], cursor: str | None, limit: int) -> tuple[list, Any]:
    """Keyset paging over `keys`, all descending: the next page is "after the last row", never an offset."""
    where = ""
    if cursor:
        values = _typed(keyset.decode(cursor), keys)
        params = params | {f"k{i}": v for i, v in enumerate(values)}
        where = f"WHERE ({', '.join(keys)}) < ({', '.join(f'%(k{i})s' for i in range(len(keys)))})"
    order = ", ".join(f"{k} DESC" for k in keys)
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            f"SELECT * FROM ({sql}) r {where} ORDER BY {order} LIMIT %(lim)s", params | {"lim": limit + 1})
        ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = keyset.encode(tuple(rows[-1][k] for k in keys)) if more and rows else None
    return rows, nxt


async def _enrich(pool, rows: list[dict]) -> list[dict]:
    ids = list({r["id"] for r in rows})
    if not ids:
        return []
    async with pool.connection() as conn:
        links = await (await conn.execute(
            f"SELECT story_id, url, host, source_type FROM news_links WHERE story_id = ANY(%s) "
            f"AND NOT {is_private_url('url')} ORDER BY id",
            (ids,))).fetchall()
        ents = await (await conn.execute("""
            SELECT e.story_id, CASE WHEN e.org_id IS NOT NULL THEN 'org' ELSE 'funder' END AS kind,
                   coalesce(o.id, f.id) AS id, coalesce(o.slug, f.slug) AS slug, coalesce(o.name, f.name) AS name,
                   e.match, e.confidence, e.stance, e.visibility
            FROM news_story_entities e LEFT JOIN orgs o ON o.id = e.org_id LEFT JOIN funders f ON f.id = e.funder_id
            WHERE e.story_id = ANY(%s) ORDER BY e.match DESC""", (ids,))).fetchall()
        places = await (await conn.execute("""
            SELECT n.story_id, l.name FROM news_story_locations n JOIN locations l ON l.id = n.location_id
            WHERE n.story_id = ANY(%s) ORDER BY l.kind DESC, l.name""", (ids,))).fetchall()
    out = []
    for r in rows:
        sid = r["id"]
        item = {k: r[k] for k in ("id", "headline", "headline_generated", "summary", "published_on", "date_source",
                                  "content_kind", "is_news", "scope", "topic", "sentiment", "main_url", "main_host",
                                  "source_type", "channel", "visibility")}
        item["area_reason"], item["row_id"] = r.get("area_reason"), r["row_id"]
        item["match_level"], item["confidence_level"] = level(r["m"], "match"), level(r["c"], "confidence")
        item["also"] = [{k: x[k] for k in ("url", "host", "source_type")} for x in links
                        if x["story_id"] == sid and x["url"] != r["main_url"]]
        item["entities"] = [
            {"kind": e["kind"], "id": e["id"], "slug": e["slug"], "name": e["name"], "stance": e["stance"],
             "visibility": e["visibility"], "match_level": level(e["match"], "match"),
             "confidence_level": level(e["confidence"], "confidence")} for e in ents if e["story_id"] == sid]
        # The entity this row is a link of, so the card leads with it and shows its stance.
        own = ("org", r.get("e_org")) if r.get("e_org") else ("funder", r.get("e_funder")) if r.get("e_funder") else None
        item["about"] = next((e for e in item["entities"] if own and (e["kind"], e["id"]) == own), None)
        item["places"] = [p["name"] for p in places if p["story_id"] == sid]
        out.append(item)
    return out


async def _counts(pool, params: dict) -> dict[str, int]:
    """All three bucket counts in one round trip; a bucket's own picker narrows only that bucket."""
    parts = []
    for b in ("org", "funder", "general"):
        parts.append(f"SELECT '{b}' AS bucket, count(*) AS n FROM "
                     f"(SELECT 1 FROM ({_base(b)} {_filters(b)}) r LIMIT {COUNT_CAP}) x")
    # The org picker's parameter appears only in the org part, the funder picker's only in the funder part.
    async with pool.connection() as conn:
        rows = await (await conn.execute(" UNION ALL ".join(parts), params)).fetchall()
    return {r["bucket"]: r["n"] for r in rows}


async def list_stories(pool, f: Filters, *, cursor: str | None, limit: int, today: date | None = None) -> dict:
    """Ordered by match, then confidence, then date (spec section 5); counts for all three buckets."""
    params = _params(f, today or datetime.now(UTC).date())
    rows, nxt = await _page(pool, _base(f.bucket) + _filters(f.bucket), params, ["m", "c", "pub", "row_id"], cursor, limit)
    # A bucket's own picker narrows only that bucket's count.
    counts = await _counts(pool, params)
    return {"items": await _enrich(pool, rows), "next_cursor": nxt, "counts": counts}


async def entity_news(pool, *, kind: Literal["org", "funder"], slug: str, cursor: str | None, limit: int) -> dict:
    """One organisation's or funder's stories, newest first, for its Registry profile."""
    f = Filters(bucket=kind, org=slug if kind == "org" else None, funder=slug if kind == "funder" else None)
    params = _params(f, datetime.now(UTC).date())
    rows, nxt = await _page(pool, _base(kind, profile=True) + _filters(kind), params, ["pub", "row_id"], cursor, limit)
    return {"items": await _enrich(pool, rows), "next_cursor": nxt}


async def last_pull(pool) -> date | None:
    """When the latest finished news pull ended, for the Media & Signals header."""
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT max(finished_at)::date AS d FROM ingest_runs "
            "WHERE status = 'finished' AND 'tavily_news' = ANY(requested_sources)")).fetchone()
    return row["d"]


async def hide(pool, story_id: int, *, org_id: int | None, funder_id: int | None, user_id: Any) -> bool:
    async with pool.connection() as conn:
        row = await (await conn.execute("""
            UPDATE news_story_entities SET visibility = 'hidden', hidden_by = %s, hidden_at = now()
            WHERE story_id = %s AND org_id IS NOT DISTINCT FROM %s AND funder_id IS NOT DISTINCT FROM %s
            RETURNING id""", (user_id, story_id, org_id, funder_id))).fetchone()
    return row is not None
