"""One news pull with the store, runner and models faked: what is searched, scored, checked and storied."""

from __future__ import annotations

import contextlib
from datetime import date
from types import SimpleNamespace

import pytest

from app.ingest.adapters.tavily_news import Hit, SearchFailed
from app.ingest.matcher import name_key
from app.ingest.news import pipeline
from app.ingest.news import run as news_run
from app.ingest.news import verify as news_verify
from app.ingest.news.bars import Bars
from app.ingest.news.classify import EntityVerdict, TopicVerdict
from app.ingest.news.feeds import Subject

TODAY = date(2026, 10, 11)
BARS = Bars(0.6, 0.8, 0.7, 0.9, 0.9, 0.95)
ORG = Subject(kind="org", id=1, key="org-1", name="Acme Trust", place="Kohima")
FEED = Subject(kind="feed", id=None, key="fcra", name="FCRA")
OLD = Subject(kind="org", id=2, key="org-2", name="Beta Society", searched_through=date(2026, 10, 1))


def hit(url, title="Acme Trust opens a weaving centre in Kohima", published=None):
    return Hit(url=url, title=title, snippet="did x", text="did x", published=published, query="q", scope="open_web")


ENTITY = {"on_target": True, "match": 0.9, "confidence": 0.95, "content_kind": "news", "is_news": True,
          "stance": "positive", "signal_type": "grant", "summary": "Acme got a grant",
          "region": {"state": "Nagaland"}, "sector_tags": ["health"]}
TOPIC = {"on_target": True, "match": 0.9, "confidence": 0.9, "topic": "fcra", "content_kind": "news",
         "is_news": True, "scope": "national", "sentiment": "neutral", "registry_named": ["Acme Trust"],
         "summary": "FCRA rules change"}


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if isinstance(self.rows, list) and self.rows else (
            None if isinstance(self.rows, list) else self.rows)

    async def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, answers):
        self.answers = answers
        self.sql: list[tuple[str, object]] = []

    async def execute(self, sql, params=None):
        self.sql.append((sql, params))
        for key, rows in self.answers.items():
            if key in sql:
                return Cursor(rows(params) if callable(rows) else rows)
        return Cursor([])

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield


class FakePool:
    def __init__(self, answers=None, run=None, claimed=True, status_after="running"):
        base = {
            "SELECT status, subjects, requested_sources": [run] if run else [],
            "SET claimed_at = now()": [{"id": 1}] if claimed else [],
            "SELECT status FROM ingest_runs": [{"status": status_after}],
            "SELECT id, status, notes, subjects": [{"status": "finished", "notes": "g", "subjects": [],
                                                    "started_at": None, "finished_at": None}],
            "FROM ingest_run_items": [{"record_kind": "news_link", "status": "inserted", "subject": "A",
                                       "reason": None},
                                      {"record_kind": "news_search", "status": "failed", "subject": "B",
                                       "reason": "502"}],
            "SELECT is_news, published_on, scope FROM news_stories": [{"is_news": True, "published_on": TODAY,
                                                                       "scope": "national"}],
            "INSERT INTO ingest_runs": [{"id": 9}],
        }
        base.update(answers or {})
        self.conn = FakeConn(base)

    @contextlib.asynccontextmanager
    async def connection(self):
        yield self.conn

    def sqls(self, needle):
        return [p for s, p in self.conn.sql if needle in s]


class FakeStore:
    def __init__(self, subjects=(), lookback=(), done=(), recent=(), names=None):
        self.subjects, self.lookback_hits, self.done, self.recent = list(subjects), list(lookback), set(done), recent
        self.names = names or {}
        self.links: dict[str, int] = {}
        self.by_id: dict[int, Hit] = {}
        self.scores: list[tuple[Subject, int, Hit, object]] = []
        self.stories: list[dict] = []
        self.calls: list[tuple] = []

    async def load_subjects(self, conn, *, org_ids, funder_ids, feeds):
        return self.subjects

    async def registry_names(self, conn):
        return self.names

    async def lookback(self, conn, s):
        return list(self.lookback_hits)

    async def scored_urls(self, conn, urls, s, version):
        return {u for u in urls if u in self.done}

    async def scored(self, conn, url, s, version):
        return False

    async def upsert_link(self, conn, h, *, run_id, content_kind, published_on, date_source):
        self.links.setdefault(h.url, len(self.links) + 1)
        self.by_id[self.links[h.url]] = h
        return self.links[h.url], "inserted"

    async def save_score(self, conn, link_id, s, version, v):
        self.scores.append((s, link_id, self.by_id[link_id], v))

    async def unstoried(self, conn, s, version, *, listed_match, floor):
        return [{"url": h.url, "original_title": h.title, "snippet": h.snippet, "verdict": v.model_dump(mode="json"),
                 "link_id": link_id, "published_on": None, "date_source": None}
                for subj, link_id, h, v in self.scores if subj == s]

    async def recent_stories(self, conn, s, *, since):
        return list(self.recent)

    async def create_story(self, conn, **fields):
        self.stories.append(fields)
        return 100 + len(self.stories)

    async def tag_places(self, conn, story_id, *, state, district):
        return ["Nowhere"] if state else []

    def __getattr__(self, name):
        async def record(*a, **k):
            self.calls.append((name, a[1:], k))
        return record


class Runner:
    def __init__(self):
        self.items: list[dict] = []

    async def record_item(self, conn, run_id, source, kind, status, **kw):
        self.items.append({"kind": kind, "status": status, **kw})

    def of(self, kind):
        return [(i["status"], i.get("reason")) for i in self.items if i["kind"] == kind]


class Model:
    def __init__(self, reply=None, fail=False, content="Written headline"):
        self.reply, self.fail, self.content, self.seen = reply, fail, content, []

    def with_structured_output(self, schema, **_):
        model = self

        class Bound:
            async def ainvoke(self, messages):
                model.seen.append(messages)
                if model.fail:
                    raise RuntimeError("model down")
                return schema.model_validate(model.reply)
        return Bound()

    async def ainvoke(self, messages):
        if self.fail:
            raise RuntimeError("down")
        return SimpleNamespace(content=self.content)


def deps(search, entity=ENTITY, topic=TOPIC, **kw):
    return pipeline.Deps(search=search, entity_model=Model(entity), topic_model=Model(topic),
                         group_model=None, headline_model=Model(), api_key="k", bars=BARS, **kw)


@pytest.fixture
def faked(monkeypatch):
    def install(store):
        runner = Runner()
        monkeypatch.setattr(pipeline, "store", store)
        monkeypatch.setattr(pipeline, "runner", runner)

        async def one_group(model, bucket, cands):
            return [[c.key] for c in cands]
        monkeypatch.setattr(pipeline, "group", one_group)
        return runner
    return install


def news_run_row(subjects, status="running", sources=("tavily_news",)):
    return {"status": status, "subjects": subjects, "requested_sources": list(sources), "claimed_at": None}


class TestRunRow:
    async def test_create_run_labels_everyone_and_chosen(self):
        pool = FakePool()
        assert await pipeline.create_run(pool, org_ids=None, funder_ids=None, feeds=["fcra"], started_by=None) == 9
        await pipeline.create_run(pool, org_ids=[1], funder_ids=[2], feeds=[], started_by="u", goal="why")
        inserts = pool.sqls("INSERT INTO ingest_runs")
        assert inserts[0][1] == ["feed:fcra", "all"] and inserts[0][3] == "News: everyone · fcra"
        assert inserts[1][1] == ["org:1", "funder:2"] and inserts[1][3] == "why (News: 2 chosen)"

    def test_parse(self):
        assert pipeline._parse(["all", "feed:fcra"]) == (None, None, ["fcra"])
        assert pipeline._parse(["org:3", "funder:4"]) == ([3], [4], [])
        with pytest.raises(pipeline.RunRefused):
            pipeline._parse([])

    async def test_select(self):
        assert (await pipeline.select(None, None)).org_ids is None
        assert await pipeline.select(None, [], ["fcra"]) == pipeline.Selection([], [], ["fcra"], [], [])
        pool = FakePool({"FROM orgs WHERE registry_status": [
            {"kind": "org", "id": 1, "name": "Acme Trust", "aliases": ["ATR"]},
            {"kind": "funder", "id": 7, "name": "Big Fund", "aliases": None}]})
        sel = await pipeline.select(pool, ["atr", "Big Fund", "Nobody"])
        assert sel == pipeline.Selection([1], [7], [], ["Acme Trust", "Big Fund"], ["Nobody"])

    async def test_plan_for(self, faked):
        faked(FakeStore(subjects=[ORG, FEED]))
        plan = await pipeline.plan_for(FakePool(), org_ids=[1], funder_ids=None, feeds=["fcra"])
        assert plan.subjects == 2 and plan.newcomers == 2

    async def test_summary_counts_and_failures(self):
        s = await pipeline.run_summary(FakePool(), 3)
        assert s["counts"] == {"news_link:inserted": 1, "news_search:failed": 1} and s["failed"] == ["B: 502"]


class TestExecuteGuards:
    async def test_missing_run(self):
        with pytest.raises(LookupError):
            await pipeline.execute_run(FakePool(), 1, deps(None), today=TODAY)

    async def test_not_a_news_run(self):
        with pytest.raises(pipeline.RunRefused):
            await pipeline.execute_run(FakePool(run=news_run_row(["all"], sources=["india_csr"])), 1, deps(None))

    async def test_a_finished_run_returns_its_summary(self):
        out = await pipeline.execute_run(FakePool(run=news_run_row(["all"], status="finished")), 1, deps(None))
        assert out["status"] == "finished"

    async def test_busy_and_stale_claims(self):
        with pytest.raises(pipeline.RunBusy):
            await pipeline.execute_run(FakePool(run=news_run_row(["org:1"]), claimed=False), 1, deps(None))
        out = await pipeline.execute_run(FakePool(run=news_run_row(["org:1"]), claimed=False, status_after="failed"),
                                         1, deps(None))
        assert out["run_id"] == 1


class TestExecuteRun:
    async def test_full_pull(self, faked):
        hits = {
            '"Acme Trust"': [hit("https://eastmojo.com/acme/1"),
                             hit("https://eastmojo.com/acme/1/"),  # same URL key: scored once
                             hit("https://www.linkedin.com/company/acme"),  # a profile page: never scored
                             hit("https://eastmojo.com/acme/old", published="Fri, 01 Jan 2021 10:00:00 GMT"),
                             hit("https://eastmojo.com/acme/done")],
        }
        searched = []

        async def search(client, *, api_key, query, scope, days, domains):
            searched.append((query, scope, days))
            return hits.get(query, [hit(f"https://eastmojo.com/feed/{len(searched)}", title="#fcra #ngo")])

        store = FakeStore(subjects=[ORG, FEED], lookback=[hit("https://eastmojo.com/acme/stored")],
                          done={"https://eastmojo.com/acme/done"}, names={name_key("Acme Trust"): ORG})
        runner = faked(store)
        pool = FakePool(run=news_run_row(["org:1", "feed:fcra"]))
        out = await pipeline.execute_run(pool, 5, deps(search), today=TODAY)

        assert out["run_id"] == 5
        scored = {(s.kind, h.url) for s, _, h, _ in store.scores}
        assert ("org", "https://eastmojo.com/acme/1") in scored and ("org", "https://eastmojo.com/acme/stored") in scored
        assert not any("linkedin" in u or u.endswith(("/old", "/done")) for _, u in scored)
        # D14: the feed item naming Acme Trust is scored for Acme too.
        assert any(s == ORG and "feed/" in h.url for s, _, h, _ in store.scores)
        assert pool.sqls("SET last_seen_at") == [(["https://eastmojo.com/acme/done"],)]
        feed_story = next(s for s in store.stories if s["feed"] == "fcra")
        assert feed_story["headline"] == "Written headline" and feed_story["headline_generated"]
        assert any(s["feed"] is None and s["scope"] == "state" for s in store.stories)
        assert pool.sqls("place_names")  # a region the gazetteer did not know is kept by name
        assert pool.sqls("topic_match = greatest")
        assert [c[0] for c in store.calls].count("advance_watch") == 2
        assert pool.sqls("finished_at = now(), status")[-1][0] == "finished"
        assert all(st in ("inserted",) for st, _ in runner.of("news_link"))

    async def test_every_search_failing_fails_the_run(self, faked):
        async def search(client, **kw):
            raise RuntimeError("no key")
        store = FakeStore(subjects=[OLD])
        runner = faked(store)
        pool = FakePool(run=news_run_row(["org:2"]))
        await pipeline.execute_run(pool, 5, deps(search), today=TODAY)
        assert pool.sqls("finished_at = now(), status")[-1][:2] == ("failed", "every search failed")
        assert runner.of("news_search")[0][0] == "failed" and "no key" in runner.of("news_search")[0][1]
        assert not store.calls

    async def test_classification_failure_and_cap_hold_the_watermark(self, faked):
        async def search(client, *, query, scope, **kw):
            return [hit("https://eastmojo.com/a"), hit("https://eastmojo.com/b")]
        store = FakeStore(subjects=[OLD])
        runner = faked(store)
        await pipeline.execute_run(FakePool(run=news_run_row(["org:2"])), 5,
                                   deps(search, max_classify=1, entity=None), today=TODAY)
        statuses = sorted(st for st, _ in runner.of("news_link"))
        assert statuses == ["failed", "refused"]
        assert "advance_watch" not in [c[0] for c in store.calls]

    async def test_one_failed_scope_still_classifies_the_other(self, faked):
        async def search(client, *, query, scope, **kw):
            if scope != "open_web":
                raise SearchFailed("502")
            return [hit("https://eastmojo.com/a")]
        store = FakeStore(subjects=[OLD])
        runner = faked(store)
        pool = FakePool(run=news_run_row(["org:2"]))
        await pipeline.execute_run(pool, 5, deps(search), today=TODAY)
        assert runner.of("news_link") == [("inserted", None)]
        assert pool.sqls("finished_at = now(), status")[-1][1] != "every search failed"

    async def test_a_crash_marks_the_run_failed_and_reraises(self, faked):
        store = FakeStore(subjects=[OLD])

        async def boom(conn, **kw):
            raise KeyError("x")
        faked(store)
        store.load_subjects = boom
        pool = FakePool(run=news_run_row(["org:2"]))
        with pytest.raises(KeyError):
            await pipeline.execute_run(pool, 5, deps(None), today=TODAY)
        assert pool.sqls("finished_at = now(), status")[-1][0] == "failed"


def verdict(**kw):
    return EntityVerdict.model_validate({**ENTITY, **kw})


class TestChecks:
    def checks(self, **kw):
        base = {"verifier": object(), "max_verify": 1, "verify_seconds": 600}
        base.update(kw)
        return pipeline._Checks(deps(None, **base), started=pipeline.time.monotonic())

    async def test_no_verifier_or_not_borderline_keeps_first(self):
        first = verdict(match=0.5)
        assert await self.checks(verifier=None).settle(None, 1, ORG, hit("u"), first) is first
        sure = verdict(match=0.95)
        assert await self.checks().settle(None, 1, ORG, hit("u"), sure) is sure

    @pytest.mark.parametrize("kw,result,why", [
        ({"max_verify": 0}, None, "cap of 0 checks"),
        ({"verify_seconds": -1}, None, "out of this run's checking time"),
        ({}, None, "ended without a verdict"),
        ({}, RuntimeError("timeout-ish"), "check failed: RuntimeError"),
    ])
    async def test_a_check_that_cannot_finish_keeps_the_first_read(self, monkeypatch, faked, kw, result, why):
        runner = faked(FakeStore())

        async def fake_verify(agent, s, h, first, *, run_id):
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(pipeline, "verify", fake_verify)
        first = verdict(match=0.5)
        assert await self.checks(**kw).settle(FakePool(), 1, ORG, hit("u"), first) is first
        assert runner.of("news_verify")[0][0] == "refused" and why in runner.of("news_verify")[0][1]

    @pytest.mark.parametrize("new_match,status", [(0.8, "updated"), (0.55, "matched")])
    async def test_a_check_records_what_moved(self, monkeypatch, faked, new_match, status):
        runner = faked(FakeStore())
        checked = verdict(match=new_match, stance="negative", evidence="read it", verified=True)

        async def fake_verify(agent, s, h, first, *, run_id):
            return checked
        monkeypatch.setattr(pipeline, "verify", fake_verify)
        got = await self.checks().settle(FakePool(), 1, ORG, hit("u"), verdict(match=0.5))
        assert got is checked
        item = runner.items[0]
        assert item["status"] == status and item["changes"]["stance"] == {"old": "positive", "new": "negative"}


class TestStories:
    def found(self, url, title="Acme Trust opens a weaving centre", link_id=1, kind=ORG, **v):
        verd = verdict(**v) if kind.kind != "feed" else TopicVerdict.model_validate({**TOPIC, **v})
        return pipeline.Found(kind, hit(url, title), verd, link_id, None, None)

    async def test_headline_keeps_a_good_title_and_falls_back_quietly(self):
        good = self.found("https://eastmojo.com/a")
        assert await pipeline._headline([good], deps(None)) == (good.hit.title, False)
        weak = self.found("https://eastmojo.com/b", title="#ngo")
        d = deps(None)
        d.headline_model = Model(fail=True)
        assert await pipeline._headline([weak], d) == (None, False)
        d.headline_model = Model(content="")
        assert await pipeline._headline([weak], d) == (None, False)

    async def test_links_already_storied_and_grouped_with_a_stored_story(self, faked, monkeypatch):
        store = FakeStore(recent=[{"id": 5, "published_on": None, "host": "eastmojo.com", "headline": "H",
                                   "summary": "S", "url": "https://eastmojo.com/s"}])
        faked(store)

        async def grouping(model, bucket, cands):
            return [["s5", "n0"], ["n1"], ["s5"]]
        monkeypatch.setattr(pipeline, "group", grouping)
        items = [self.found("https://eastmojo.com/old", link_id=1), self.found("https://eastmojo.com/x", link_id=2),
                 self.found("https://eastmojo.com/y", link_id=3, stance="negative", region={})]
        pool = FakePool({"SELECT id, story_id FROM news_links": [{"id": 1, "story_id": 77}, {"id": 2, "story_id": None}]})
        await pipeline._stories_for(pool, ORG, items, deps(None), TODAY)
        touched = [c[1][0] for c in store.calls if c[0] == "touch_story"]
        assert sorted(touched) == [5, 77] and len(store.stories) == 1
        attached = {c[1][0]: c[1][1] for c in store.calls if c[0] == "attach_links"}
        assert attached == {77: [1], 5: [2], 101: [3]}
        assert len([c for c in store.calls if c[0] == "upsert_entity_link"]) == 3

    async def test_a_story_that_fails_is_recorded_and_others_continue(self, faked):
        store = FakeStore()

        async def bad(conn, s, version, **kw):
            if s == OLD:
                raise ValueError("bad row")
            return []
        runner = faked(store)
        store.unstoried = bad
        failed: set[str] = set()
        await pipeline._build_stories(FakePool(), 1, [OLD, FEED], deps(None), TODAY, failed)
        assert failed == {"org:2"} and runner.of("news_story") == [("failed", "ValueError: bad row")]


class TestDepsAndHelpers:
    def test_from_settings(self, monkeypatch):
        from app.agent import models
        monkeypatch.setattr(models, "resolve_model", lambda name: f"m:{name}")
        monkeypatch.setattr(news_verify, "build_verifier", lambda s: "verifier")
        s = pipeline.get_settings().model_copy(update={"news_verify_max": 3, "utility_model": "u",
                                                       "research_model": "r"})
        d = pipeline.Deps.from_settings(s)
        assert d.entity_model == "m:u" and d.group_model == "m:r" and d.verifier == "verifier" and d.max_verify == 3
        off = pipeline.Deps.from_settings(s.model_copy(update={"news_verify_max": 0}))
        assert off.verifier is None

    def test_topic_story_fields_and_key(self):
        v = TopicVerdict.model_validate(TOPIC)
        assert pipeline.topic_story_fields(v)["scope"] == "national"
        assert pipeline._key(FEED) == "feed:fcra" and pipeline._key(ORG) == "org:1"
        assert pipeline.entity_story_fields(verdict(region={"state": "A", "district": "B"}))["scope"] == "district"
        assert pipeline.entity_story_fields(verdict(region={}))["scope"] == "national"

    def test_hit_date_ignores_bad_and_social_publisher_dates(self):
        assert pipeline._hit_date(hit("https://eastmojo.com/a", published="not a date")) == (None, None)
        assert pipeline._hit_date(hit("https://www.instagram.com/p/x", published="Fri, 09 Oct 2026 10:00:00 GMT")) \
            == (None, None)
        assert pipeline._date(hit("https://eastmojo.com/a"), verdict()) == (None, None)


class TestVerify:
    first = verdict(match=0.5, confidence=0.6, on_target=False)

    def test_build_verifier_is_read_only(self, monkeypatch):
        import deepagents

        from app.agent import models
        seen = {}

        class Agent:
            def with_config(self, config):
                seen["config"] = config
                return "configured"

        def create(**kw):
            seen.update(kw)
            return Agent()
        monkeypatch.setattr(deepagents, "create_deep_agent", create)
        monkeypatch.setattr(models, "resolve_model", lambda name: f"m:{name}")
        s = pipeline.get_settings().model_copy(update={"research_model": "r", "model": "r"})
        assert news_verify.build_verifier(s) == "configured"
        assert [t.name for t in seen["tools"]] == ["read_page", "search_public_sources"]
        assert seen["model"] == "m:r" and seen["response_format"] is news_verify.Check
        assert seen["config"]["recursion_limit"] == news_verify.RECURSION_LIMIT

    class Agent:
        def __init__(self, result):
            self.result, self.config = result, None

        async def ainvoke(self, payload, config):
            self.config = config
            return self.result

    async def test_no_structured_response(self):
        agent = self.Agent({"messages": []})
        assert await news_verify.verify(agent, ORG, hit("https://a.org/x"), self.first) is None
        assert "langfuse_session_id" not in agent.config["metadata"]

    async def test_a_raise_without_a_page_read_is_not_applied(self):
        check = news_verify.Check(on_target=True, match=0.9, confidence=0.9, stance="negative",
                                  evidence="x" * 300, evidence_url="https://a.org/x")
        agent = self.Agent({"structured_response": check, "messages": []})
        out = await news_verify.verify(agent, ORG, hit("https://a.org/x"), self.first, run_id=4)
        assert out.verified and out.match == 0.5 and not out.on_target and out.stance == "negative"
        assert "raise not applied" in out.evidence and len(check.evidence) == 200
        assert agent.config["metadata"]["langfuse_session_id"] == "news-run-4"

    async def test_a_raise_backed_by_a_read_page_is_applied(self):
        check = news_verify.Check(on_target=True, match=0.9, confidence=0.9, stance="positive",
                                  evidence_url="https://a.org/x/")
        msgs = [SimpleNamespace(tool_calls=[{"id": "t1", "name": "read_page", "args": {"url": "https://a.org/x"}}]),
                SimpleNamespace(tool_call_id="t1", content="Page text about Acme")]
        out = await news_verify.verify(self.Agent({"structured_response": check, "messages": msgs}), ORG,
                                       hit("https://a.org/x"), self.first)
        assert out.match == 0.9 and out.on_target

    def test_read_needs_a_successful_read_of_that_url(self):
        calls = [SimpleNamespace(tool_calls=[{"id": "t1", "name": "read_page", "args": {"url": "https://a.org"}}])]
        assert not news_verify._read(calls, None)
        assert not news_verify._read(calls + [SimpleNamespace(tool_call_id="t1", content="REFUSED: x")],
                                     "https://a.org")
        assert not news_verify._read(calls + [SimpleNamespace(tool_call_id="t1", content="ok")], "https://b.org")


class FakeMakePool:
    def __init__(self, answers=None):
        self.inner = FakePool(answers)
        self.closed = False

    async def open(self):
        pass

    async def close(self):
        self.closed = True

    def connection(self):
        return self.inner.connection()


class TestNewsCli:
    @pytest.fixture
    def cli(self, monkeypatch):
        state = {"flushed": 0}
        made = FakeMakePool({"SELECT id FROM orgs": [{"id": 1}], "SELECT id FROM funders": []})
        monkeypatch.setattr(news_run, "make_pool", lambda url, max_size: made)
        monkeypatch.setattr(news_run, "configure_langfuse", lambda s: None)
        monkeypatch.setattr(news_run, "flush_traces", lambda: state.__setitem__("flushed", state["flushed"] + 1))

        async def plan_for(pool, **kw):
            return SimpleNamespace(line="2 searches")
        monkeypatch.setattr(news_run.pipeline, "plan_for", plan_for)
        state["pool"] = made
        return state

    async def test_visibility_only(self, monkeypatch, cli, capsys):
        async def recompute(conn, bars):
            return {"public": 1}
        monkeypatch.setattr(news_run.store, "recompute_visibility", recompute)
        assert await news_run.main([], [], visibility_only=True) == 0
        assert "{'public': 1}" in capsys.readouterr().out and cli["pool"].closed and cli["flushed"] == 1

    async def test_everyone_without_yes_is_refused(self, cli, capsys):
        assert await news_run.main([], []) == 2
        assert "CONFIRM=1" in capsys.readouterr().out

    async def test_a_chosen_org_runs(self, monkeypatch, cli, capsys):
        async def create_run(pool, **kw):
            assert kw["org_ids"] == [1] and kw["funder_ids"] == [] and kw["feeds"] == []
            return 3

        async def execute_run(pool, run_id, deps):
            return {"run_id": run_id, "when": date(2026, 1, 1)}
        monkeypatch.setattr(news_run.pipeline, "create_run", create_run)
        monkeypatch.setattr(news_run.pipeline, "execute_run", execute_run)
        monkeypatch.setattr(news_run.pipeline.Deps, "from_settings", classmethod(lambda cls, s: None))
        assert await news_run.main(["acme"], []) == 0
        out = capsys.readouterr().out
        assert "plan: 2 searches" in out and '"run_id": 3' in out and "2026-01-01" in out

