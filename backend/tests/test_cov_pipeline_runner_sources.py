"""The adapter runner over a fake pool, and the source registry's path rules and self-check."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from datetime import UTC, date, datetime, timedelta

import pytest

from app.ingest import runner
from app.ingest import sources as src
from app.ingest.adapters._http import SourceUnavailable
from app.ingest.sources import AccessRule, Category


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, answers):
        self.answers, self.sql = answers, []

    async def execute(self, sql, params=None):
        self.sql.append((sql, params))
        for key, rows in self.answers.items():
            if key in sql:
                return Cursor(rows)
        return Cursor([])

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield


class FakePool:
    def __init__(self, answers=None):
        self.conn = FakeConn(answers or {})

    @contextlib.asynccontextmanager
    async def connection(self):
        yield self.conn

    def items(self):
        return [p for s, p in self.conn.sql if "INSERT INTO ingest_run_items" in s]

    def updates(self):
        return [(s, p) for s, p in self.conn.sql if s.startswith("UPDATE ingest_runs")]


STARTED = datetime(2026, 10, 1, tzinfo=UTC)


def run_row(requested, finished=True):
    return {"id": 4, "started_at": STARTED, "finished_at": STARTED + timedelta(seconds=12) if finished else None,
            "status": "finished", "requested_sources": requested, "subjects": ["Acme"], "fiscal_years": [],
            "notes": "goal"}


@pytest.fixture
def pool(monkeypatch):
    p = FakePool({"INSERT INTO ingest_runs": [{"id": 4}], "FROM ingest_runs WHERE id": [run_row(["nse_brsr"])]})
    monkeypatch.setattr(runner, "get_pool", lambda: p)
    return p


class TestRunner:
    def test_max_concurrent_sources_follows_settings(self):
        assert runner.max_concurrent_sources() == runner.get_settings().db_gate_slots

    async def test_catalog_baseline(self, monkeypatch):
        p = FakePool({"SELECT (SELECT count(*)": [{"funders": 3, "documents": 1}]})
        monkeypatch.setattr(runner, "get_pool", lambda: p)
        assert await runner.catalog_baseline() == {"funders": 3, "documents": 1}

    async def test_run_import_refuses_unknown_held_and_parked_and_runs_each_pair(self, monkeypatch, pool):
        calls = []

        async def adapter(conn, run_id, *, model, limit, subject, fiscal_year):
            calls.append((subject, fiscal_year))
            if subject == "Bad":
                raise SourceUnavailable("site down")
            if subject == "Worse":
                raise ValueError("parse")
        monkeypatch.setitem(runner.ADAPTERS, "nse_brsr", adapter)
        held = next(s.key for s in src.SOURCES.values() if not s.dispatchable)
        out = await runner.run_import(["nse_brsr", "nope", held, "gdelt"], goal="g",
                                      funders=["Acme", "Bad", "Worse"], years=["FY24"])
        assert sorted(calls) == [("Acme", "FY24"), ("Bad", "FY24"), ("Worse", "FY24")]
        items = pool.items()
        reasons = [i[4] for i in items]
        assert "No source named 'nope' is registered." in reasons
        assert any(i[2] == "run_scope" and i[5] == "1 sources held by their access rule" for i in items)
        assert runner.PARKED["gdelt"] in reasons
        assert "site down" in reasons and "ValueError: parse" in reasons
        assert any("for 'Bad' FY24" in (i[5] or "") for i in items)
        assert "status = 'finished'" in pool.updates()[-1][0]
        assert out["run_id"] == 4

    async def test_a_cancelled_run_is_marked_failed(self, monkeypatch, pool):
        async def adapter(conn, run_id, **kw):
            raise asyncio.CancelledError()
        monkeypatch.setitem(runner.ADAPTERS, "nse_brsr", adapter)
        with pytest.raises(asyncio.CancelledError):
            await runner.run_import(["nse_brsr"], goal="g")
        sql, params = pool.updates()[-1]
        assert "status = 'failed'" in sql and params == ("cancelled", 4)

    def test_runnable_for(self, monkeypatch):
        assert runner.runnable_for(None) == frozenset(runner.ADAPTERS)
        assert "tavily_news" in runner.runnable_for(["tavily_news"])

    async def test_record_item_serialises_changes(self):
        conn = FakeConn({})
        await runner.record_item(conn, 1, "s", "k", "added", changes={"when": date(2026, 1, 1)})
        assert conn.sql[0][1][8] == '{"when": "2026-01-01"}'

    async def test_summarise_missing_run(self, monkeypatch):
        monkeypatch.setattr(runner, "get_pool", lambda: FakePool())
        assert await runner.summarise(9) == {"error": "no import run with id 9"}

    async def test_summarise_seeds_attempted_sources_and_sorts_out_the_rest(self, monkeypatch):
        held = next(s.key for s in src.SOURCES.values() if not s.dispatchable)
        p = FakePool({
            "FROM ingest_runs WHERE id": [run_row(["nse_brsr", "samhita", "tavily_news", held], finished=False)],
            "GROUP BY 1, 2": [{"source": "samhita", "status": "failed", "n": 1},
                              {"source": "samhita", "status": "added", "n": 2},
                              {"source": "x", "status": "added", "n": 1}],
            "IN ('queued', 'failed', 'refused')": [{"source": "samhita", "status": "failed"}],
            "IN ('added', 'updated')": [{"source": "samhita", "status": "added"}],
        })
        monkeypatch.setattr(runner, "get_pool", lambda: p)
        monkeypatch.setitem(runner.ADAPTERS, "nse_brsr", object())
        monkeypatch.setattr(runner, "RUNNABLE", frozenset({"nse_brsr", "samhita", "tavily_news"}))
        out = await runner.summarise(4)
        assert out["sources_processed"] == ["nse_brsr", "tavily_news"]
        assert out["sources_failed"] == ["samhita"] and out["sources_refused"] == [held]
        assert out["by_source"]["nse_brsr"] == {} and out["totals"] == {"failed": 1, "added": 3}
        assert out["duration_seconds"] > 0 and out["written"] == [{"source": "samhita", "status": "added"}]

    async def test_summarise_of_everything_lists_unbuilt_sources(self, monkeypatch):
        p = FakePool({"FROM ingest_runs WHERE id": [run_row([])]})
        monkeypatch.setattr(runner, "get_pool", lambda: p)
        out = await runner.summarise(4)
        assert out["duration_seconds"] == 12.0
        assert set(out["sources_without_adapter"]) == {s.key for s in src.dispatchable()} - runner.ADAPTERS.keys()


GUIDESTAR = src.SOURCES["guidestar_india"]
GIVE = src.SOURCES["give_do"]
API = "https://guidestarindia.frappe.cloud/api/method/guidestar.api.npo_profile.npo_profile_search"


class TestPathRefusal:
    @pytest.mark.parametrize("url,why", [
        ("http://give.do/discover/x", "only https"),
        ("https://u:p@give.do/discover/x", "user name or password"),
        ("https://give.do:8443/discover/x", "naming a port"),
        ("https://give.do:99999/discover/x", "naming a port"),
        ("https://other.org/discover/x", "only give.do itself"),
        ("https://give.do/discover/%2541", "still encoded"),
        ("https://give.do/discover/x;y", "carries ';'"),
        ("https://give.do/discover/../discover/x", "'.', '..' or '//'"),
        ("https://give.do/discover/login", "sign-in or account page"),
        ("https://give.do/about", "only /discover/ may be read"),
        ("https://give.do/discover/", "only /discover/ may be read"),
    ])
    def test_refusals(self, url, why):
        assert why in GIVE.path_refusal(url)

    def test_allowed(self):
        assert GIVE.path_refusal("https://give.do/discover/acme") is None
        assert GUIDESTAR.path_refusal(API + "?keyword=acme&page_no=1") is None

    @pytest.mark.parametrize("query,why", [
        ("keyword=a&keyword=b", "repeated query parameter"),
        ("evil=1", "'evil' is not one this source allows"),
    ])
    def test_query_rules(self, query, why):
        assert why in GUIDESTAR.path_refusal(f"{API}?{query}")

    def test_pinned_query_values(self):
        index = src.SOURCES["org_grant_intelligence_index"]
        base = "https://api.github.com/repos/project-tech4dev/org-grant-intelligence/contents"
        assert "must be given, pinned" in index.path_refusal(base)
        assert "ref must be" in index.path_refusal(base + "?ref=main")
        assert index.path_refusal(base + "?ref=414cd6968765bcfff758632797dcbb8d00363ab2") is None


class TestRegistry:
    def test_helpers(self):
        assert src.normal_path("/a//b/./c/") == ("/a/b/c/", None)
        assert src.normal_path("/a\\b")[1] is not None
        assert src.url_host("https://WWW.Give.do./x") == "give.do"
        assert src.url_host("http://a\x00b/") == "a\x00b"  # httpx refuses it; urlsplit's host stands in
        assert all(Category.MEDIA in s.categories for s in src.in_category(Category.MEDIA))
        assert src.rule_for_host("unknown.example") is None
        assert src.rule_for_host("www.give.do")[1].key == "give"  # the strictest product on the host wins
        assert src.resolve(None)[0] == list(src.SOURCES.values())
        assert src.resolve(["give_do", "zz"]) == ([GIVE], ["zz"])

    def test_rule_for_url(self):
        assert src.rule_for_url("https://nowhere.example/x") is None
        assert src.rule_for_url("https://give.do/discover/a")[1] is GIVE
        # A non-normal path is governed by every entry on the host, the strictest first.
        rule, _ = src.rule_for_url("https://give.do/discover/%2541")
        assert rule is not None
        gh = src.rule_for_url("https://github.com/project-tech4dev/org-grant-intelligence/blob/x")
        assert gh[1].key == "org_grant_intelligence_github"
        assert src.SOURCES["org_grant_intelligence_github"].governs("/project-tech4dev/org-grant-intelligence@v1")

    def test_site_class(self):
        assert any(s.is_site_class for s in src.SOURCES.values())


def bad(**kw):
    base = dataclasses.replace(GIVE)
    return dataclasses.replace(base, **kw)


class TestSelfCheck:
    @pytest.mark.parametrize("sources,why", [
        ((GIVE, GIVE), "duplicate source key"),
        ((bad(basis="short"),), "basis is a verdict"),
        ((bad(categories=frozenset()),), "belongs to no category"),
        ((bad(yields=("gold",)),), "unknown yield kinds"),
        ((bad(host="a b"),), "is not a bare host"),
        ((bad(access_rule=AccessRule.OPEN_API, host=""),), "dispatchable but names no host"),
        ((bad(access_rule=AccessRule.OPEN_API, robots_checked_at=None),), "nobody recorded a robots check"),
        ((bad(allowed_paths=()),), "names one host and the paths"),
        ((bad(robots_checked_at=None),), "path-scoped but nobody recorded"),
        ((bad(allowed_paths=("/",)),), "is not a normal path"),
        ((bad(access_rule=AccessRule.NOT_CHECKED),), "belong to path-scoped sources only"),
        ((bad(access_rule=AccessRule.NOT_CHECKED, allowed_paths=(), governs_paths=("/A",)),), "governs_paths is for"),
    ])
    def test_each_contradiction_raises(self, monkeypatch, sources, why):
        monkeypatch.setattr(src, "_SOURCES", sources)
        with pytest.raises(ValueError, match=why):
            src._self_check()

    def test_the_real_inventory_passes(self):
        src._self_check()
        assert src.SOURCES["give_do"].robots_checked_at <= datetime.now(UTC).date()
