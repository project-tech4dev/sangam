"""One run end to end, and the repeat-pull rule (D15): run A and B, then A to D."""

import re
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.ingest.adapters.tavily_news import Hit, SearchFailed
from app.ingest.news import pipeline
from app.ingest.news.bars import Bars
from app.ingest.news.classify import EntityVerdict, Region
from tests.test_rls import DSN

TODAY = date(2026, 10, 11)
NUMBER = re.compile(r"Repeatpull\w+?(\d) Foundation")


def test_entity_fields_take_scope_from_the_region_and_topic_from_the_signal():
    v = EntityVerdict(on_target=True, match=0.9, confidence=0.9, content_kind="news", is_news=True,
                      stance="negative", signal_type="regulatory", region=Region(state="Assam"), summary="s")
    assert pipeline.entity_story_fields(v).items() >= {"topic": "fcra", "scope": "state",
                                                       "sentiment": "negative"}.items()


class Fakes:
    """Search returns the subject's own link and one shared link; the model says every item is on target."""

    def __init__(self, fail_for=()):
        self.searches, self.classified, self.fail_for = [], [], set(fail_for)

    async def search(self, client, *, api_key, query, days, scope, domains, **_):
        self.searches.append((query, days))
        if any(name in query for name in self.fail_for):
            raise SearchFailed("502")
        name = re.search(r"Repeatpull\w+", query).group(0)  # unique per test run: links never leak across tests
        return [Hit(url=f"https://eastmojo.com/{name}/1", title=f"Organisation {name} opens a weaving centre",
                    snippet="did x", text="did x", published=None, query=query, scope=scope),
                Hit(url=f"https://eastmojo.com/shared-{name[:-1]}", title="Two organisations share a stage",
                    snippet="both orgs", text="both orgs", published=None, query=query, scope=scope)]

    def model(self, reply):
        fakes = self

        class M:
            schema = None

            def with_structured_output(self, schema, **_):
                bound = M()
                bound.schema = schema
                return bound

            async def ainvoke(self, messages):
                if self.schema is None:  # a plain call, as write_headline makes
                    return SimpleNamespace(content="A headline")
                if self.schema.__name__ in ("EntityVerdict", "TopicVerdict"):  # grouping calls are not scoring
                    fakes.classified.append(messages[1][1][:60])
                return self.schema.model_validate(reply)
        return M()


ON = {"on_target": True, "match": 0.9, "confidence": 0.95, "content_kind": "news", "is_news": True,
      "stance": "positive", "signal_type": "other", "summary": "s"}


@pytest.fixture
async def pool():
    p = AsyncConnectionPool(DSN, kwargs={"row_factory": dict_row, "autocommit": True}, open=False)
    try:
        await p.open(wait=True, timeout=3)
    except Exception:  # noqa: BLE001 - any failure to connect means no scratch database here
        pytest.skip("Postgres not reachable")
    yield p
    await p.close()


async def _orgs(pool, n, tag):
    async with pool.connection() as c:
        return [(await (await c.execute(
            "INSERT INTO orgs (slug, name) VALUES (%s, %s) RETURNING id",
            (f"rp-{tag}-{i}", f"Repeatpull{tag}{i} Foundation"))).fetchone())["id"] for i in range(n)]


def _deps(f):
    grouper = f.model({"groups": []})
    return pipeline.Deps(search=f.search, entity_model=f.model(ON), topic_model=None, group_model=grouper,
                         headline_model=f.model(ON), api_key="k", bars=Bars(0.6, 0.8, 0.7, 0.9, 0.9, 0.95),
                         parallel_searches=2, parallel_classify=2)


def _number(query):
    return NUMBER.search(query).group(1)


@pytest.mark.integration
async def test_repeat_pulls_score_only_what_is_new(pool):
    tag = uuid4().hex[:6]
    a, b, c, d = await _orgs(pool, 4, tag)
    f = Fakes()
    run1 = await pipeline.create_run(pool, org_ids=[a, b], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run1, _deps(f), today=TODAY)
    first = len(f.classified)
    assert all(days == 90 for _, days in f.searches)
    assert first == 4  # each org: its own link and the shared one

    f.searches.clear()
    run2 = await pipeline.create_run(pool, org_ids=[a, b, c, d], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run2, _deps(f), today=TODAY)
    assert len(f.classified) - first == 4  # only C and D; A and B were scored already
    days = {_number(q): d for q, d in f.searches}
    assert days["0"] == 1 and days["2"] == 90  # A from its watermark, C from 90 days back

    async with pool.connection() as conn:
        shared = await (await conn.execute("""
            SELECT count(DISTINCT c.org_id) AS scored, count(DISTINCT l.story_id) AS stories
            FROM news_links l JOIN news_link_scores c ON c.link_id = l.id
            WHERE l.url = %s AND c.org_id = ANY(%s)""", (f"https://eastmojo.com/shared-Repeatpull{tag}", [a, b, c, d]))
        ).fetchone()
        assert shared == {"scored": 4, "stories": 1}
        linked = await (await conn.execute(
            "SELECT count(DISTINCT e.org_id) AS n FROM news_story_entities e JOIN news_links l "
            "ON l.story_id = e.story_id WHERE l.url = %s AND e.org_id = ANY(%s)",
            (f"https://eastmojo.com/shared-Repeatpull{tag}", [a, b, c, d]))).fetchone()
        assert linked["n"] == 4


@pytest.mark.integration
async def test_a_failed_search_leaves_that_watermark_and_the_others_move(pool):
    tag = uuid4().hex[:6]
    a, b = await _orgs(pool, 2, tag)
    f = Fakes(fail_for={f"Repeatpull{tag}0"})
    run = await pipeline.create_run(pool, org_ids=[a, b], funder_ids=[], feeds=[], started_by=None)
    summary = await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    async with pool.connection() as conn:
        marks = {r["org_id"]: r["searched_through"] for r in await (await conn.execute(
            "SELECT org_id, searched_through FROM news_watch WHERE org_id = ANY(%s)", ([a, b],))).fetchall()}
    assert marks == {b: TODAY}
    assert summary["status"] == "finished"


@pytest.mark.integration
async def test_executing_a_run_twice_does_not_search_again(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    f = Fakes()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    first = await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    searched = len(f.searches)
    again = await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    assert len(f.searches) == searched and again["counts"] == first["counts"]


@pytest.mark.integration
async def test_an_item_dated_before_the_floor_is_neither_classified_nor_stored(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    old_post = f"https://x.com/someone{tag}/status/{(1700000000000 - 1288834974657) << 22}"  # Nov 2023

    class OldFakes(Fakes):
        async def search(self, client, *, api_key, query, days, scope, domains, **_):
            return [Hit(url=old_post, title="Organisation opens a weaving centre in Udalguri", snippet="x",
                        text="x", published=None, query=query, scope=scope)]

    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(OldFakes()), today=TODAY)
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT l.story_id, (SELECT count(*) FROM news_link_scores c WHERE c.link_id = l.id) AS scores "
            "FROM news_links l WHERE l.url = %s", (old_post,))).fetchone()
    assert row is None  # dated before the floor: dropped before classification, so never stored


@pytest.mark.integration
async def test_a_profile_page_is_never_classified_or_stored(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    profile = f"https://in.linkedin.com/in/someone-{tag}"

    class ProfileFakes(Fakes):
        async def search(self, client, *, api_key, query, days, scope, domains, **_):
            return [Hit(url=profile, title="Someone - Project Manager", snippet="x", text="x", published=None,
                        query=query, scope=scope)]

    f = ProfileFakes()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT count(*) AS n FROM news_links WHERE url = %s", (profile,))).fetchone()
    assert f.classified == [] and row["n"] == 0


@pytest.mark.integration
async def test_a_run_that_names_nobody_is_refused_not_turned_into_everyone(pool):
    run = await pipeline.create_run(pool, org_ids=[], funder_ids=[], feeds=[], started_by=None)
    with pytest.raises(pipeline.RunRefused, match="names nobody"):
        await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)


@pytest.mark.integration
async def test_an_import_run_is_not_executed_as_a_news_run(pool):
    async with pool.connection() as conn:
        run = (await (await conn.execute(
            "INSERT INTO ingest_runs (requested_sources, subjects) VALUES ('{india_csr}', '{Some Funder}') "
            "RETURNING id")).fetchone())["id"]
    with pytest.raises(pipeline.RunRefused, match="not a news run"):
        await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)


@pytest.mark.integration
async def test_two_executes_of_one_run_search_once(pool):
    import asyncio

    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    f = Fakes()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    results = await asyncio.gather(pipeline.execute_run(pool, run, _deps(f), today=TODAY),
                                   pipeline.execute_run(pool, run, _deps(f), today=TODAY), return_exceptions=True)
    assert sum(isinstance(r, pipeline.RunBusy) for r in results) == 1
    assert len(f.searches) == 2  # one org, one query, two scopes: searched once



def test_dates_follow_d10_post_id_then_publisher_then_text():
    v = EntityVerdict(on_target=True, match=0.9, confidence=0.9, content_kind="news", is_news=True,
                      stance="neutral", signal_type="other", event_date=date(2026, 7, 1), summary="s")
    news = Hit(url="https://eastmojo.com/a", title="t", snippet="", text="", query="q", scope="open_web",
               published="Fri, 09 Oct 2026 10:00:00 GMT")
    assert pipeline._date(news, v) == (date(2026, 10, 9), "publisher")
    undated = Hit(url="https://eastmojo.com/b", title="t", snippet="", text="", query="q", scope="open_web",
                  published=None)
    assert pipeline._date(undated, v) == (date(2026, 7, 1), "text")


class Raising(Fakes):
    """Classification raises for every item: the pairs fail and must be retried."""

    def model(self, reply):
        inner = super().model(reply)

        class Down:
            def with_structured_output(self, schema, **_):
                if schema.__name__ == "EntityVerdict":
                    return self
                return inner.with_structured_output(schema)

            async def ainvoke(self, messages):
                raise RuntimeError("model down")
        return Down()


async def _watermark(pool, org):
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT searched_through FROM news_watch WHERE org_id = %s",
                                        (org,))).fetchone()
    return row and row["searched_through"]


@pytest.mark.integration
async def test_a_failed_classification_holds_the_watermark_and_is_scored_next_run(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(Raising()), today=TODAY)
    assert await _watermark(pool, a) is None
    f = Fakes()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    assert len(f.classified) == 2 and await _watermark(pool, a) == TODAY


@pytest.mark.integration
async def test_a_malformed_search_reply_fails_only_its_subject(pool):
    tag = uuid4().hex[:6]
    a, b = await _orgs(pool, 2, tag)

    class Malformed(Fakes):
        async def search(self, client, *, query, **kw):
            if f"Repeatpull{tag}0" in query:
                raise ValueError("not JSON")
            return await super().search(client, query=query, **kw)

    run = await pipeline.create_run(pool, org_ids=[a, b], funder_ids=[], feeds=[], started_by=None)
    summary = await pipeline.execute_run(pool, run, _deps(Malformed()), today=TODAY)
    assert summary["status"] == "finished"
    assert await _watermark(pool, a) is None and await _watermark(pool, b) == TODAY


@pytest.mark.integration
async def test_a_story_that_failed_to_build_is_built_next_run_without_reclassifying(pool, monkeypatch):
    from app.ingest.news import store

    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    real = store.create_story

    async def broken(*args, **kw):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr(store, "create_story", broken)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)
    assert await _watermark(pool, a) is None
    monkeypatch.setattr(store, "create_story", real)
    f = Fakes()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    async with pool.connection() as conn:
        n = (await (await conn.execute(
            "SELECT count(*) AS n FROM news_story_entities WHERE org_id = %s", (a,))).fetchone())["n"]
    assert f.classified == [] and n == 2


@pytest.mark.integration
async def test_a_hit_published_before_the_floor_is_not_classified(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)

    class Stale(Fakes):
        async def search(self, client, *, query, scope, **kw):
            return [Hit(url=f"https://eastmojo.com/{tag}/old", title="An old report from last year", snippet="x",
                        text="x", published="Mon, 06 Jan 2025 10:00:00 GMT", query=query, scope=scope)]

    f = Stale()
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    assert f.classified == []


@pytest.mark.integration
async def test_the_classification_cap_holds_the_watermark(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    f = Fakes()
    deps = _deps(f)
    deps.max_classify = 1
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    summary = await pipeline.execute_run(pool, run, deps, today=TODAY)
    assert len(f.classified) == 1 and await _watermark(pool, a) is None
    assert summary["counts"].get("news_link:refused") == 1



@pytest.mark.integration
async def test_a_stale_claim_returns_the_failed_summary_not_busy(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    async with pool.connection() as conn:
        await conn.execute("UPDATE ingest_runs SET claimed_at = now() - interval '1 hour' WHERE id = %s", (run,))
    summary = await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)
    assert summary["status"] == "failed"


@pytest.mark.integration
async def test_a_run_created_and_never_executed_expires(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    old = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    async with pool.connection() as conn:
        await conn.execute("UPDATE ingest_runs SET started_at = now() - interval '1 hour' WHERE id = %s", (old,))
    await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    async with pool.connection() as conn:
        status = (await (await conn.execute("SELECT status FROM ingest_runs WHERE id = %s", (old,))).fetchone())
    assert status["status"] == "failed"


@pytest.mark.integration
async def test_a_story_whose_writes_fail_leaves_nothing_half_written(pool, monkeypatch):
    from app.ingest.news import store

    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)

    async def broken(*args, **kw):
        raise RuntimeError("tagging failed")
    monkeypatch.setattr(store, "tag_sectors", broken)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT count(*) AS n FROM news_stories WHERE headline LIKE %s", (f"%Repeatpull{tag}%",))).fetchone()
    assert row["n"] == 0


@pytest.mark.integration
async def test_links_carry_provenance_and_a_stable_content_hash(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    await pipeline.execute_run(pool, run, _deps(Fakes()), today=TODAY)
    async with pool.connection() as conn:
        link = await (await conn.execute(
            "SELECT source_name, content_hash, extractor_version FROM news_links WHERE url = %s",
            (f"https://eastmojo.com/Repeatpull{tag}0/1",))).fetchone()
    assert link["source_name"] == "tavily_news" and link["content_hash"] and link["extractor_version"]


@pytest.mark.integration
async def test_select_matches_names_and_aliases_and_reports_the_rest(pool):
    tag = uuid4().hex[:6]
    async with pool.connection() as conn:
        org = (await (await conn.execute(
            "INSERT INTO orgs (slug, name, aliases) VALUES (%s, %s, %s) RETURNING id",
            (f"sel-{tag}", f"Selectable {tag} Trust", [f"SEL{tag}"]))).fetchone())["id"]
    chosen = await pipeline.select(pool, [f"sel{tag}", f"Nobody {tag}"])
    assert chosen.org_ids == [org] and chosen.funder_ids == [] and chosen.feeds == []
    assert chosen.matched == [f"Selectable {tag} Trust"] and chosen.unmatched == [f"Nobody {tag}"]
    everyone = await pipeline.select(pool, [])
    assert everyone.org_ids is None and set(everyone.feeds) == {"fcra", "csr_trends", "ngo_north_east"}


@pytest.mark.integration
async def test_a_run_where_every_search_failed_is_failed_not_a_last_pull(pool):
    tag = uuid4().hex[:6]
    a, b = await _orgs(pool, 2, tag)
    f = Fakes(fail_for={f"Repeatpull{tag}"})
    run = await pipeline.create_run(pool, org_ids=[a, b], funder_ids=[], feeds=[], started_by=None)
    summary = await pipeline.execute_run(pool, run, _deps(f), today=TODAY)
    assert summary["status"] == "failed" and not f.classified
    async with pool.connection() as conn:
        notes = (await (await conn.execute("SELECT notes FROM ingest_runs WHERE id = %s", (run,))).fetchone())["notes"]
    assert "every search failed" in notes


@pytest.mark.integration
async def test_a_run_already_marked_failed_is_never_turned_back_into_finished(pool):
    tag = uuid4().hex[:6]
    (a,) = await _orgs(pool, 1, tag)
    run = await pipeline.create_run(pool, org_ids=[a], funder_ids=[], feeds=[], started_by=None)
    async with pool.connection() as conn:
        await conn.execute("UPDATE ingest_runs SET status = 'failed', finished_at = now() WHERE id = %s", (run,))
    await pipeline._finish(pool, run, "finished", None)
    async with pool.connection() as conn:
        status = (await (await conn.execute("SELECT status FROM ingest_runs WHERE id = %s", (run,))).fetchone())
    assert status["status"] == "failed"


@pytest.mark.integration
async def test_a_hidden_registry_record_is_reported_unmatched_not_pulled_for_nothing(pool):
    tag = uuid4().hex[:6]
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO orgs (slug, name, registry_status) VALUES (%s, %s, 'hidden')",
                           (f"hid-{tag}", f"Hiddenorg {tag}"))
    chosen = await pipeline.select(pool, [f"Hiddenorg {tag}"])
    assert chosen.org_ids == [] and chosen.unmatched == [f"Hiddenorg {tag}"]
