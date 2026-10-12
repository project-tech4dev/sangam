"""Reading stories: keyset paging with no repeats, bucket counts, the signed-out view, and staff hiding a match."""

import json
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.db.pool import CallerPool
from app.repositories import news_stories as repo
from tests.test_rls import DSN

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool():
    p = AsyncConnectionPool(DSN, kwargs={"row_factory": dict_row, "autocommit": True}, open=False)
    try:
        await p.open(wait=True, timeout=3)
    except Exception:  # noqa: BLE001 - any failure to connect means no scratch database here
        pytest.skip("Postgres not reachable")
    yield p
    await p.close()


async def _world(pool):
    tag = uuid4().hex[:8]
    async with pool.connection() as c:
        org = (await (await c.execute("INSERT INTO orgs (slug, name) VALUES (%s, %s) RETURNING id, slug",
                                      (f"ns-{tag}", f"Newsorg {tag}"))).fetchone())
        for headline, match, vis in [("high", 0.95, "public"), ("mid", 0.8, "listed"), ("low", 0.65, "listed")]:
            s = (await (await c.execute(
                "INSERT INTO news_stories (headline, topic, summary, is_news) VALUES (%s, 'other', %s, true) RETURNING id",
                (f"{headline} {tag}", f"about {tag}"))).fetchone())["id"]
            link = (await (await c.execute(
                "INSERT INTO news_links (url, host, source_type, story_id) VALUES (%s, 'a.com', 'online news', %s) "
                "RETURNING id", (f"https://a.com/{tag}/{headline}", s))).fetchone())["id"]
            await c.execute("UPDATE news_stories SET main_link_id = %s, source_url = %s WHERE id = %s",
                            (link, f"https://a.com/{tag}/{headline}", s))
            await c.execute("INSERT INTO news_story_entities (story_id, org_id, match, confidence, visibility) "
                            "VALUES (%s, %s, %s, 0.95, %s)", (s, org["id"], match, vis))
    return org, tag


async def test_pages_follow_the_order_with_no_repeat_and_count_the_bucket(pool):
    org, _ = await _world(pool)
    f = repo.Filters(bucket="org", org=org["slug"], staff=True)
    page1 = await repo.list_stories(pool, f, cursor=None, limit=2)
    assert [s["headline"].split()[0] for s in page1["items"]] == ["high", "mid"]
    page2 = await repo.list_stories(pool, f, cursor=page1["next_cursor"], limit=2)
    assert [s["headline"].split()[0] for s in page2["items"]] == ["low"] and page2["next_cursor"] is None
    assert page1["counts"]["org"] == 3
    assert page1["items"][0]["entities"][0]["match_level"] == "High"


async def test_signed_out_sees_only_the_public_story_on_a_profile(pool):
    org, _ = await _world(pool)
    anon = CallerPool(pool, role="anon", claims="")
    page = await repo.entity_news(anon, kind="org", slug=org["slug"], cursor=None, limit=10)
    assert [s["headline"].split()[0] for s in page["items"]] == ["high"]


async def test_staff_hide_a_wrong_match(pool):
    org, tag = await _world(pool)
    async with pool.connection() as c:
        story = (await (await c.execute("SELECT id FROM news_stories WHERE headline = %s", (f"high {tag}",)))
                 .fetchone())["id"]
    assert await repo.hide(pool, story, org_id=org["id"], funder_id=None, user_id=None)
    anon = CallerPool(pool, role="anon", claims=json.dumps({}))
    page = await repo.entity_news(anon, kind="org", slug=org["slug"], cursor=None, limit=10)
    assert page["items"] == []


async def test_general_leaves_out_a_topic_story_the_bars_hid_even_with_a_public_entity_link(pool):
    org, tag = await _world(pool)
    async with pool.connection() as c:
        s = (await (await c.execute(
            "INSERT INTO news_stories (headline, topic, feed, visibility, topic_match, topic_confidence) "
            "VALUES (%s, 'fcra', 'fcra', 'hidden', 0.9, 0.9) RETURNING id", (f"hiddentopic {tag}",))).fetchone())["id"]
        await c.execute("INSERT INTO news_story_entities (story_id, org_id, match, confidence, visibility) "
                        "VALUES (%s, %s, 0.95, 0.95, 'public')", (s, org["id"]))
    member = await repo.list_stories(pool, repo.Filters(bucket="general", q=f"hiddentopic {tag}"), cursor=None,
                                     limit=10)
    staff = await repo.list_stories(pool, repo.Filters(bucket="general", q=f"hiddentopic {tag}", staff=True),
                                    cursor=None, limit=10)
    assert member["items"] == [] and staff["items"] == []


async def test_a_cursor_of_the_wrong_types_is_refused_as_a_bad_cursor(pool):
    from app.repositories import keyset

    with pytest.raises(ValueError, match="cursor"):
        await repo.list_stories(pool, repo.Filters(bucket="general"), cursor=keyset.encode(("a", "b", "c", "d")),
                                limit=5)



async def test_the_org_bucket_filters_on_that_orgs_own_stance(pool):
    org, tag = await _world(pool)
    async with pool.connection() as c:
        await c.execute("UPDATE news_stories SET sentiment = 'positive' WHERE headline LIKE %s", (f"% {tag}",))
        await c.execute("UPDATE news_story_entities SET stance = 'negative' WHERE org_id = %s", (org["id"],))
    neg = await repo.list_stories(pool, repo.Filters(bucket="org", org=org["slug"], sentiment="negative", staff=True),
                                  cursor=None, limit=10)
    assert len(neg["items"]) == 3


async def _member(pool, org_id: int, tag: str) -> CallerPool:
    """A signed-in member of one organisation, as CallerPool runs a request."""
    sub = str(uuid4())
    async with pool.connection() as c:
        uid = (await (await c.execute("INSERT INTO users (email, auth_user_id) VALUES (%s, %s) RETURNING id",
                                      (f"m-{tag}@news.test", sub))).fetchone())["id"]
        await c.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'member')", (uid, org_id))
    return CallerPool(pool, role="authenticated", claims=json.dumps({"sub": sub}))


async def test_my_organisations_is_the_members_own_and_staff_see_every_one(pool):
    mine, _ = await _world(pool)
    other, tag = await _world(pool)
    member = await _member(pool, mine["id"], tag)
    page = await repo.list_stories(member, repo.Filters(bucket="org"), cursor=None, limit=50)
    assert {e["slug"] for s in page["items"] for e in s["entities"]} == {mine["slug"]}
    assert page["counts"]["org"] == 3
    staff = await repo.list_stories(pool, repo.Filters(bucket="org", staff=True), cursor=None, limit=500)
    assert {mine["slug"], other["slug"]} <= {e["slug"] for s in staff["items"] for e in s["entities"]}


async def _topic(c, tag: str, headline: str, *, feed: str, scope: str, topic: str = "ngo_news",
                 kind: str = "news", state: str | None = None) -> None:
    s = (await (await c.execute(
        "INSERT INTO news_stories (headline, topic, feed, scope, content_kind, is_news, visibility, topic_match, "
        "topic_confidence) VALUES (%s, %s, %s, %s, %s, true, 'listed', 0.9, 0.9) RETURNING id",
        (f"{headline} {tag}", topic, feed, scope, kind))).fetchone())["id"]
    if state:
        await c.execute("INSERT INTO news_story_locations (story_id, location_id) "
                        "SELECT %s, id FROM locations WHERE kind = 'state' AND name = %s", (s, state))


async def test_my_area_is_own_states_north_east_civil_society_and_national_policy(pool):
    org, tag = await _world(pool)
    async with pool.connection() as c:
        for name in ("Assam", "Meghalaya", "Kerala"):
            if not await (await c.execute("SELECT 1 FROM locations WHERE kind = 'state' AND name = %s",
                                          (name,))).fetchone():
                await c.execute("INSERT INTO locations (kind, name) VALUES ('state', %s)", (name,))
        await c.execute("INSERT INTO org_locations (org_id, location_id) "
                        "SELECT %s, id FROM locations WHERE kind = 'state' AND name = 'Assam'", (org["id"],))
        await _topic(c, tag, "ownstate", feed="csr_trends", scope="state", topic="csr_funding", state="Assam")
        await _topic(c, tag, "necivil", feed="ngo_north_east", scope="state", state="Meghalaya")
        await _topic(c, tag, "policy", feed="fcra", scope="national", topic="fcra")
        await _topic(c, tag, "explainer", feed="fcra", scope="national", topic="fcra", kind="background")
        await _topic(c, tag, "kerala", feed="csr_trends", scope="state", topic="csr_funding", state="Kerala")
    member = await _member(pool, org["id"], tag)

    async def heads(area):
        page = await repo.list_stories(member, repo.Filters(bucket="general", area=area, q=tag), cursor=None, limit=50)
        return {s["headline"].split()[0]: s["area_reason"] for s in page["items"]}

    assert await heads("mine") == {"ownstate": "Assam", "necivil": "Meghalaya · North East civil society",
                                   "policy": "National policy"}
    assert set(await heads("north_east")) == {"ownstate", "necivil"}
    assert set(await heads("all")) == {"ownstate", "necivil", "policy", "explainer", "kerala"}


async def test_last_pull_is_the_latest_finished_news_run(pool):
    async with pool.connection() as c:
        ids = [r["id"] for r in await (await c.execute(
            "INSERT INTO ingest_runs (requested_sources, status, finished_at) "
            "VALUES ('{tavily_news}', 'finished', '2031-01-02'), ('{tavily_news}', 'failed', '2031-02-01'), "
            "('{india_csr}', 'finished', '2031-03-01') RETURNING id")).fetchall()]
    try:
        assert str(await repo.last_pull(pool)) == "2031-01-02"
    finally:
        async with pool.connection() as c:
            await c.execute("DELETE FROM ingest_runs WHERE id = ANY(%s)", (ids,))


async def test_each_row_carries_its_own_entity_and_stance(pool):
    a, tag = await _world(pool)
    async with pool.connection() as c:
        b = (await (await c.execute("INSERT INTO orgs (slug, name) VALUES (%s, %s) RETURNING id, slug",
                                    (f"nb-{tag}", f"Otherorg {tag}"))).fetchone())
        s = (await (await c.execute("SELECT id FROM news_stories WHERE headline = %s", (f"mid {tag}",))).fetchone())["id"]
        await c.execute("UPDATE news_story_entities SET stance = 'negative' WHERE story_id = %s", (s,))
        await c.execute("INSERT INTO news_story_entities (story_id, org_id, match, confidence, stance, visibility) "
                        "VALUES (%s, %s, 0.99, 0.99, 'positive', 'listed')", (s, b["id"]))
    page = await repo.list_stories(pool, repo.Filters(bucket="org", sentiment="negative", q=tag, staff=True),
                                   cursor=None, limit=10)
    mine = [i for i in page["items"] if i["id"] == s]
    assert len(mine) == 1 and mine[0]["about"]["slug"] == a["slug"] and mine[0]["about"]["stance"] == "negative"
    assert isinstance(mine[0]["row_id"], int)


async def test_background_and_hidden_stories_reach_no_list_not_even_staffs(pool):
    org, tag = await _world(pool)
    async with pool.connection() as c:
        await c.execute("UPDATE news_story_entities SET visibility = 'hidden' WHERE story_id = "
                        "(SELECT id FROM news_stories WHERE headline = %s)", (f"mid {tag}",))
        await c.execute("UPDATE news_stories SET is_news = false WHERE headline = %s", (f"low {tag}",))
        await c.execute("UPDATE news_stories SET is_news = true WHERE headline IN (%s, %s)",
                        (f"high {tag}", f"mid {tag}"))
        await _topic(c, tag, "belowbar", feed="fcra", scope="national", topic="fcra")
        await c.execute("UPDATE news_stories SET visibility = 'hidden' WHERE headline = %s", (f"belowbar {tag}",))
    staff = repo.Filters(bucket="org", org=org["slug"], staff=True)
    heads = [s["headline"].split()[0] for s in (await repo.list_stories(pool, staff, cursor=None, limit=10))["items"]]
    assert heads == ["high"]
    profile = await repo.entity_news(pool, kind="org", slug=org["slug"], cursor=None, limit=10)
    assert [s["headline"].split()[0] for s in profile["items"]] == ["high"]
    general = await repo.list_stories(pool, repo.Filters(bucket="general", q=tag, staff=True), cursor=None, limit=10)
    assert general["items"] == []


async def test_a_profile_shows_only_public_stories_to_everyone_signed_in_or_not(pool):
    org, tag = await _world(pool)
    member = await _member(pool, org["id"], tag)
    for reader in (pool, member):
        page = await repo.entity_news(reader, kind="org", slug=org["slug"], cursor=None, limit=10)
        assert [s["headline"].split()[0] for s in page["items"]] == ["high"]
