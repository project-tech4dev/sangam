"""The store against Postgres: one link per URL, a score per subject, watermarks, look-back, places."""

from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.ingest.adapters.tavily_news import Hit
from app.ingest.news import store
from app.ingest.news.classify import EntityVerdict
from app.ingest.news.feeds import Subject
from tests.test_rls import DSN

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():
    try:
        c = await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    try:
        yield c
    finally:
        await c.rollback()
        await c.close()


async def _org(conn, name, aliases=()):
    row = await (await conn.execute(
        "INSERT INTO orgs (slug, name, aliases) VALUES (%s, %s, %s) RETURNING id",
        (f"t-{uuid4().hex[:8]}", name, list(aliases)))).fetchone()
    return Subject(kind="org", id=row["id"], key=str(row["id"]), name=name, aliases=tuple(aliases))


def _hit(url, title="t", snippet="s"):
    return Hit(url=url, title=title, snippet=snippet, text=snippet, published=None, query="q", scope="open_web")


VERDICT = EntityVerdict(on_target=True, match=0.9, confidence=0.9, content_kind="news", is_news=True,
                        stance="neutral", signal_type="other", summary="x")


async def test_one_link_per_url_and_one_score_per_subject(conn):
    a, b = await _org(conn, "Org A"), await _org(conn, "Org B")
    run = (await (await conn.execute("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")).fetchone())["id"]
    link, status = await store.upsert_link(conn, _hit("https://x.com/a/status/1"), run_id=run, content_kind="news",
                                           published_on=None, date_source=None)
    again, status2 = await store.upsert_link(conn, _hit("https://x.com/a/status/1"), run_id=run, content_kind="news",
                                             published_on=None, date_source=None)
    assert (link, status, status2) == (again, "added", "matched")
    await store.save_score(conn, link, a, "v1", VERDICT)
    assert await store.scored(conn, "https://x.com/a/status/1", a, "v1")
    assert not await store.scored(conn, "https://x.com/a/status/1", b, "v1")
    assert not await store.scored(conn, "https://x.com/a/status/1", a, "v2")


async def test_the_watermark_and_the_subject_list(conn):
    a = await _org(conn, "Org Watch")
    subs = await store.load_subjects(conn, org_ids=[a.id], funder_ids=[], feeds=["fcra"])
    assert [s.kind for s in subs] == ["org", "feed"] and subs[0].searched_through is None  # feeds are shared
    await store.advance_watch(conn, a, date(2026, 10, 11))
    subs = await store.load_subjects(conn, org_ids=[a.id], funder_ids=[], feeds=[])
    assert subs[0].searched_through == date(2026, 10, 11)


async def test_lookback_finds_stored_links_naming_a_newcomer_even_with_an_apostrophe(conn):
    name = f"People's Endeavour {uuid4().hex[:6]}"
    newcomer = await _org(conn, name)
    run = (await (await conn.execute("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")).fetchone())["id"]
    await store.upsert_link(conn, _hit("https://a.com/1", title=f"{name} wins award"), run_id=run,
                            content_kind="news", published_on=None, date_source=None)
    await store.upsert_link(conn, _hit("https://a.com/2", title="Unrelated"), run_id=run,
                            content_kind="news", published_on=None, date_source=None)
    found = await store.lookback(conn, newcomer)
    assert [h.url for h in found] == ["https://a.com/1"]


async def test_places_resolve_or_come_back_as_names(conn):
    story = await store.create_story(conn, headline="h", topic="other")
    left = await store.tag_places(conn, story, state="Assam", district="Udalguri")
    rows = await (await conn.execute(
        "SELECT l.kind FROM news_story_locations n JOIN locations l ON l.id = n.location_id WHERE story_id = %s",
        (story,))).fetchall()
    assert sorted(r["kind"] for r in rows) == ["district", "state"] and left == []
    assert await store.tag_places(conn, story, state="Atlantis", district=None) == ["Atlantis"]


async def test_visibility_is_recomputed_and_a_staff_hide_stands(conn):
    from app.ingest.news.bars import Bars

    a = await _org(conn, "Org Recompute")
    profile = await store.create_story(conn, headline="directory page", topic="other", is_news=False)
    hidden = await store.create_story(conn, headline="news", topic="other", is_news=True,
                                      published_on=date(2026, 10, 1))
    topic = await store.create_story(conn, headline="explainer", topic="fcra", feed="fcra", is_news=False,
                                     topic_match=0.9, topic_confidence=0.9, visibility="listed")
    for sid in (profile, hidden):
        await store.upsert_entity_link(conn, sid, a, match=0.95, confidence=0.95, stance="neutral",
                                       signal_type="other", visibility="listed")
    await conn.execute("UPDATE news_story_entities SET visibility = 'hidden', hidden_by = NULL, hidden_at = now() "
                       "WHERE story_id = %s", (hidden,))
    await conn.execute("UPDATE news_story_entities SET hidden_by = (SELECT id FROM users LIMIT 1) "
                       "WHERE story_id = %s", (hidden,))
    await store.recompute_visibility(conn, Bars(0.6, 0.8, 0.7, 0.9, 0.9, 0.95))
    rows = {r["story_id"]: r["visibility"] for r in await (await conn.execute(
        "SELECT story_id, visibility FROM news_story_entities WHERE org_id = %s", (a.id,))).fetchall()}
    assert rows == {profile: "hidden", hidden: "hidden"}
    vis = (await (await conn.execute("SELECT visibility FROM news_stories WHERE id = %s", (topic,))).fetchone())
    assert vis["visibility"] == "hidden"



async def test_a_story_hash_depends_on_its_content_not_its_time(conn):
    one = await store.create_story(conn, headline="same", topic="other", summary="s", fetched_at=date(2026, 1, 1))
    two = await store.create_story(conn, headline="same", topic="other", summary="s", fetched_at=date(2026, 2, 1))
    rows = await (await conn.execute("SELECT content_hash FROM news_stories WHERE id = ANY(%s)",
                                     ([one, two],))).fetchall()
    assert rows[0]["content_hash"] == rows[1]["content_hash"]


async def test_scored_urls_answers_for_many_urls_in_one_query(conn):
    a = await _org(conn, "Org Batch")
    run = (await (await conn.execute("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")).fetchone())["id"]
    tag = uuid4().hex[:6]
    link, _ = await store.upsert_link(conn, _hit(f"https://b.com/{tag}/1"), run_id=run, content_kind="news",
                                      published_on=None, date_source=None)
    await store.save_score(conn, link, a, "v1", VERDICT)
    got = await store.scored_urls(conn, [f"https://b.com/{tag}/1", f"https://b.com/{tag}/2"], a, "v1")
    assert got == {f"https://b.com/{tag}/1"}


async def test_an_entity_link_never_drops_its_score_so_a_shown_row_cannot_reappear(conn):
    a = await _org(conn, "Org Steady")
    sid = await store.create_story(conn, headline="steady", topic="other", is_news=True)
    await store.upsert_entity_link(conn, sid, a, match=0.8, confidence=0.9, stance="neutral",
                                   signal_type="other", visibility="listed")
    await store.upsert_entity_link(conn, sid, a, match=0.8, confidence=0.81, stance="negative",
                                   signal_type="other", visibility="listed")
    row = await (await conn.execute("SELECT confidence, stance FROM news_story_entities WHERE story_id = %s",
                                    (sid,))).fetchone()
    assert abs(row["confidence"] - 0.9) < 1e-6 and row["stance"] == "neutral"


async def test_a_later_verdict_dates_a_link_stored_undated_but_never_redates_it(conn):
    run = (await (await conn.execute("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")).fetchone())["id"]
    url = f"https://eastmojo.com/{uuid4().hex}"
    link, _ = await store.upsert_link(conn, _hit(url), run_id=run, content_kind="news", published_on=None,
                                      date_source=None)
    await store.upsert_link(conn, _hit(url), run_id=run, content_kind="news", published_on=date(2026, 10, 2),
                            date_source="text")
    await store.upsert_link(conn, _hit(url), run_id=run, content_kind="news", published_on=date(2026, 9, 1),
                            date_source="text")
    row = await (await conn.execute("SELECT published_on, date_source FROM news_links WHERE id = %s",
                                    (link,))).fetchone()
    assert (row["published_on"], row["date_source"]) == (date(2026, 10, 2), "text")
