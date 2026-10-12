"""Every database write and read the news pipeline makes, on the owner pool (RLS is for readers)."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from app.ingest.adapters.tavily_news import Hit
from app.ingest.geography import canonical_state, district_key
from app.ingest.matcher import name_key
from app.ingest.news import links
from app.ingest.news.feeds import FEEDS, Subject

COLLECTOR_VERSION = "tavily_news/v1"


def _hash(*parts: Any) -> str:
    return hashlib.sha256("\n".join(str(p or "") for p in parts).encode()).hexdigest()


def _cols(s: Subject) -> tuple[int | None, int | None, str | None]:
    return (s.id if s.kind == "org" else None, s.id if s.kind == "funder" else None,
            s.key if s.kind == "feed" else None)


async def _all(conn: Any, sql: str, params: Any = None) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def load_subjects(conn: Any, *, org_ids: list[int] | None, funder_ids: list[int] | None,
                        feeds: list[str]) -> list[Subject]:
    everyone = org_ids is None and funder_ids is None
    orgs = await _all(conn, """
        SELECT o.id, o.slug, o.name, o.aliases, o.description, w.searched_through,
               coalesce(d.name || ', ' || s.name, s.name, d.name) AS place
        FROM orgs o
        LEFT JOIN locations d ON d.id = o.registered_location_id
        LEFT JOIN locations s ON s.id = CASE WHEN d.kind = 'district' THEN d.parent_id ELSE d.id END
        LEFT JOIN news_watch w ON w.org_id = o.id
        WHERE o.registry_status IS DISTINCT FROM 'hidden' AND (%(all)s OR o.id = ANY(%(ids)s))
        ORDER BY o.id""", {"all": everyone, "ids": org_ids or []})
    funders = await _all(conn, """
        SELECT f.id, f.slug, f.name, f.aliases, w.searched_through
        FROM funders f LEFT JOIN news_watch w ON w.funder_id = f.id
        WHERE f.registry_status IS DISTINCT FROM 'hidden' AND (%(all)s OR f.id = ANY(%(ids)s))
        ORDER BY f.id""", {"all": everyone, "ids": funder_ids or []})
    marks = {r["feed"]: r["searched_through"] for r in await _all(
        conn, "SELECT feed, searched_through FROM news_watch WHERE feed IS NOT NULL")}
    return (
        [Subject("org", r["id"], r["slug"], r["name"], tuple(r["aliases"] or ()), r["place"], r["description"],
                 r["searched_through"]) for r in orgs]
        + [Subject("funder", r["id"], r["slug"], r["name"], tuple(r["aliases"] or ()),
                   searched_through=r["searched_through"]) for r in funders]
        + [Subject("feed", None, k, FEEDS[k].label, searched_through=marks.get(k)) for k in feeds]
    )


async def registry_names(conn: Any) -> dict[str, Subject]:
    out: dict[str, Subject] = {}
    for s in await load_subjects(conn, org_ids=None, funder_ids=None, feeds=[]):
        for n in (s.name, *s.aliases):
            out.setdefault(name_key(n), s)
    return out


async def lookback(conn: Any, s: Subject, limit: int = 50) -> list[Hit]:
    patterns = [f"%{n}%" for n in (s.name, *s.aliases) if n]
    rows = await _all(conn, """
        SELECT url, original_title, snippet FROM news_links
        WHERE original_title ILIKE ANY(%s) OR snippet ILIKE ANY(%s)
        ORDER BY last_seen_at DESC LIMIT %s""", (patterns, patterns, limit))
    return [Hit(url=r["url"], title=r["original_title"], snippet=r["snippet"] or "", text=r["snippet"] or "",
                published=None, query="stored links", scope="stored") for r in rows]


async def scored(conn: Any, url: str, s: Subject, version: str) -> bool:
    org, funder, feed = _cols(s)
    row = await (await conn.execute("""
        SELECT 1 FROM news_link_scores c JOIN news_links l ON l.id = c.link_id
        WHERE l.url = %s AND c.prompt_version = %s AND c.org_id IS NOT DISTINCT FROM %s
          AND c.funder_id IS NOT DISTINCT FROM %s AND c.feed IS NOT DISTINCT FROM %s""",
        (url, version, org, funder, feed))).fetchone()
    return row is not None


async def scored_urls(conn: Any, urls: list[str], s: Subject, version: str) -> set[str]:
    """Which of these URLs are already scored for this subject at this version, in one query."""
    if not urls:
        return set()
    org, funder, feed = _cols(s)
    rows = await _all(conn, """
        SELECT l.url FROM news_link_scores c JOIN news_links l ON l.id = c.link_id
        WHERE l.url = ANY(%s) AND c.prompt_version = %s AND c.org_id IS NOT DISTINCT FROM %s
          AND c.funder_id IS NOT DISTINCT FROM %s AND c.feed IS NOT DISTINCT FROM %s""",
        (urls, version, org, funder, feed))
    return {r["url"] for r in rows}


async def upsert_link(conn: Any, hit: Hit, *, run_id: int, content_kind: str | None, published_on: date | None,
                      date_source: str | None) -> tuple[int, str]:
    row = await (await conn.execute("""
        INSERT INTO news_links (url, host, source_type, original_title, snippet, published_on, date_source, run_id,
                                source_name, content_hash, extractor_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'tavily_news', %s, %s)
        ON CONFLICT (url) DO UPDATE SET last_seen_at = now(),
          -- another subject's verdict may date a link the first left undated; a stored date is never changed
          published_on = coalesce(news_links.published_on, EXCLUDED.published_on),
          date_source = CASE WHEN news_links.published_on IS NULL THEN EXCLUDED.date_source
                             ELSE news_links.date_source END
        RETURNING id, (xmax = 0) AS inserted""",
        (hit.url, links.host(hit.url), links.source_type(hit.url, content_kind), hit.title,
         (hit.snippet or "")[:1000] or None, published_on, date_source, run_id,
         _hash(hit.url, hit.title, hit.snippet), COLLECTOR_VERSION))).fetchone()
    return row["id"], "added" if row["inserted"] else "matched"


async def save_score(conn: Any, link_id: int, s: Subject, version: str, verdict: Any) -> None:
    org, funder, feed = _cols(s)
    await conn.execute("""
        INSERT INTO news_link_scores (link_id, org_id, funder_id, feed, prompt_version, on_target, match, confidence,
                                      verdict)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (link_id, org_id, funder_id, feed, prompt_version) DO NOTHING""",
        (link_id, org, funder, feed, version, verdict.on_target, verdict.match, verdict.confidence,
         verdict.model_dump_json()))


async def recent_stories(conn: Any, s: Subject, *, since: date) -> list[dict]:
    org, funder, feed = _cols(s)
    return await _all(conn, """
        SELECT st.id, st.headline, coalesce(st.summary, '') AS summary, coalesce(st.source_url, '') AS url,
               coalesce(st.main_host, '') AS host, st.published_on
        FROM news_stories st
        WHERE st.last_seen_at >= %(since)s AND (
              (%(feed)s::text IS NOT NULL AND st.feed = %(feed)s)
           OR EXISTS (SELECT 1 FROM news_story_entities e WHERE e.story_id = st.id
                      AND e.org_id IS NOT DISTINCT FROM %(org)s AND e.funder_id IS NOT DISTINCT FROM %(funder)s
                      AND %(feed)s::text IS NULL))
        ORDER BY st.last_seen_at DESC LIMIT 200""", {"since": since, "org": org, "funder": funder, "feed": feed})


async def create_story(conn: Any, **fields: Any) -> int:
    # Of what the story says, not when it was read, so the same story hashes the same on every run.
    fields.setdefault("content_hash", _hash(fields.get("headline"), fields.get("summary"), fields.get("source_url")))
    cols = ", ".join(fields)
    marks = ", ".join(["%s"] * len(fields))
    row = await (await conn.execute(f"INSERT INTO news_stories ({cols}) VALUES ({marks}) RETURNING id",
                                    tuple(fields.values()))).fetchone()
    return row["id"]


async def attach_links(conn: Any, story_id: int, link_ids: list[int]) -> None:
    await conn.execute("UPDATE news_links SET story_id = %s WHERE id = ANY(%s)", (story_id, link_ids))


async def touch_story(conn: Any, story_id: int) -> None:
    await conn.execute("UPDATE news_stories SET last_seen_at = now() WHERE id = %s", (story_id,))


async def set_main_link(conn: Any, story_id: int) -> None:
    rows = await _all(conn, "SELECT id, url, host, source_type FROM news_links WHERE story_id = %s", (story_id,))
    if not rows:
        return
    best = min(rows, key=lambda r: (links.best_link_rank(r["source_type"]), r["id"]))
    await conn.execute(
        "UPDATE news_stories SET main_link_id = %s, main_host = %s, source_url = %s WHERE id = %s",
        (best["id"], best["host"], best["url"], story_id))


async def upsert_entity_link(conn: Any, story_id: int, s: Subject, *, match: float, confidence: float,
                             stance: str | None, signal_type: str | None, visibility: str) -> None:
    org, funder, _ = _cols(s)
    await conn.execute("""
        INSERT INTO news_story_entities (story_id, org_id, funder_id, match, confidence, stance, signal_type, visibility)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (story_id, org_id, funder_id) DO UPDATE SET
          match = EXCLUDED.match, confidence = EXCLUDED.confidence, stance = EXCLUDED.stance,
          signal_type = EXCLUDED.signal_type,
          visibility = CASE WHEN news_story_entities.hidden_by IS NOT NULL THEN 'hidden' ELSE EXCLUDED.visibility END
        WHERE (EXCLUDED.match, EXCLUDED.confidence) >= (news_story_entities.match, news_story_entities.confidence)""",
        (story_id, org, funder, match, confidence, stance, signal_type, visibility))


async def tag_places(conn: Any, story_id: int, *, state: str | None, district: str | None) -> list[str]:
    unmatched: list[str] = []
    canonical = canonical_state(state) if state else None
    state_row = None
    if canonical:
        state_row = await (await conn.execute(
            "SELECT id FROM locations WHERE kind = 'state' AND name = %s", (canonical,))).fetchone()
    if state and not state_row:
        unmatched.append(state)
    ids = [state_row["id"]] if state_row else []
    if district:
        row = None
        if state_row:
            row = await (await conn.execute("""
                SELECT id FROM locations WHERE kind = 'district' AND parent_id = %s
                  AND (regexp_replace(lower(name), '[^a-z0-9]', '', 'g') = %s
                       OR EXISTS (SELECT 1 FROM unnest(aliases) a
                                  WHERE regexp_replace(lower(a), '[^a-z0-9]', '', 'g') = %s))
                LIMIT 1""", (state_row["id"], district_key(district), district_key(district)))).fetchone()
        if row:
            ids.append(row["id"])
        else:
            unmatched.append(district)
    for location_id in ids:
        await conn.execute("INSERT INTO news_story_locations VALUES (%s, %s) ON CONFLICT DO NOTHING",
                           (story_id, location_id))
    return unmatched


async def tag_sectors(conn: Any, story_id: int, sectors: list[str]) -> None:
    await conn.execute("""
        INSERT INTO news_story_tags (story_id, tag_id)
        SELECT %s, id FROM tags WHERE kind = 'domain' AND code = ANY(%s) AND status <> 'deprecated'
        ON CONFLICT DO NOTHING""", (story_id, sectors))


async def advance_watch(conn: Any, s: Subject, through: date) -> None:
    org, funder, feed = _cols(s)
    await conn.execute("""
        INSERT INTO news_watch (org_id, funder_id, feed, searched_through) VALUES (%s, %s, %s, %s)
        ON CONFLICT (org_id, funder_id, feed) DO UPDATE SET searched_through = EXCLUDED.searched_through""",
        (org, funder, feed, through))


async def recompute_visibility(conn: Any, bars: Any) -> dict[str, int]:
    """Rewrite every visibility from the stored scores (make news-visibility): a bar or a rule changed.
    A match staff hid stays hidden."""
    from app.ingest.news.bars import topic_visibility, visibility

    changed = {"entity_links": 0, "topic_stories": 0}
    for r in await _all(conn, """
        SELECT e.id, e.match, e.confidence, e.stance, e.visibility, s.is_news, s.published_on
        FROM news_story_entities e JOIN news_stories s ON s.id = e.story_id WHERE e.hidden_by IS NULL"""):
        new = visibility(r["match"], r["confidence"], sentiment=r["stance"], is_news=r["is_news"], bars=bars,
                         dated=r["published_on"] is not None)
        if new != r["visibility"]:
            await conn.execute("UPDATE news_story_entities SET visibility = %s WHERE id = %s", (new, r["id"]))
            changed["entity_links"] += 1
    for r in await _all(conn, """
        SELECT id, topic_match, topic_confidence, is_news, published_on, scope, visibility
        FROM news_stories WHERE feed IS NOT NULL"""):
        new = topic_visibility(r["topic_match"] or 0, r["topic_confidence"] or 0, is_news=r["is_news"],
                               dated=r["published_on"] is not None, scope=r["scope"], bars=bars)
        if new != r["visibility"]:
            await conn.execute("UPDATE news_stories SET visibility = %s WHERE id = %s", (new, r["id"]))
            changed["topic_stories"] += 1
    return changed


async def unstoried(conn: Any, s: Subject, version: str, *, listed_match: float, floor: date) -> list[dict]:
    """On-target links scored for this subject that are not yet in a story for it: no story at all, or (for an
    organisation or funder) a story another subject made without this one's link. Built from here, so a crash resumes."""
    org, funder, feed = _cols(s)
    return await _all(conn, """
        SELECT l.id AS link_id, l.url, l.original_title, l.snippet, l.published_on, l.date_source, c.verdict
        FROM news_link_scores c JOIN news_links l ON l.id = c.link_id
        WHERE c.prompt_version = %(v)s AND c.on_target AND c.match >= %(m)s
          AND c.org_id IS NOT DISTINCT FROM %(org)s AND c.funder_id IS NOT DISTINCT FROM %(funder)s
          AND c.feed IS NOT DISTINCT FROM %(feed)s AND (l.published_on IS NULL OR l.published_on >= %(floor)s)
          AND (l.story_id IS NULL OR (%(feed)s::text IS NULL AND NOT EXISTS (
                SELECT 1 FROM news_story_entities e WHERE e.story_id = l.story_id
                  AND e.org_id IS NOT DISTINCT FROM %(org)s AND e.funder_id IS NOT DISTINCT FROM %(funder)s)))
        ORDER BY l.id""", {"v": version, "m": listed_match, "org": org, "funder": funder, "feed": feed,
                           "floor": floor})
