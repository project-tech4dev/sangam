"""make calls-pull: candidates, extraction, page reading and the per-funder report, all with fakes."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta

import httpx
import pytest

from app.core.egress import EgressRefused
from app.ingest.calls import extract, find, pull
from app.ingest.calls import run as calls_run


class Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class FakeConn:
    """Answers each SQL by the first matching key in `answers`; records every statement."""

    def __init__(self, answers=None):
        self.answers = answers or {}
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
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def connection(self):
        yield self.conn


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def with_structured_output(self, schema, **_):
        model = self

        class Bound:
            async def ainvoke(self, messages):
                model.seen.append(messages)
                reply = model.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return schema.model_validate(reply)
        return Bound()


class TestExtract:
    def test_call_validators_drop_unknown_codes_and_partial_dates(self):
        c = extract.Call(title="Grant", deadline="2026-11", domains=["health", "nope"],
                         themes=["skilling", "zzz"])
        assert c.deadline is None and c.domains == ["health"] and c.themes == ["skilling"]

    def test_prompt_has_themes_substituted(self):
        assert "{themes}" not in extract._prompt("extract")

    async def test_extract_calls_drops_short_titles_and_truncates_page(self):
        model = FakeModel({"calls": [{"title": "Big health grant"}, {"title": " ab "}]})
        out = await extract.extract_calls(model, funder="F", url="u", text="x" * 50_000)
        assert [c.title for c in out] == ["Big health grant"]
        assert len(model.seen[0][1][1]) < 31_000

    async def test_pick_page_never_returns_a_url_it_was_not_given(self):
        cands = [("https://a.org/calls", "Calls")]
        assert await extract.pick_page(FakeModel({"url": "https://a.org/calls"}), funder="F",
                                       candidates=cands) == "https://a.org/calls"
        assert await extract.pick_page(FakeModel({"url": "https://evil.org"}), funder="F",
                                       candidates=cands) is None


class FakeSearch:
    result: object = None

    def __init__(self, **kw):
        FakeSearch.kw = kw

    async def ainvoke(self, q):
        if isinstance(FakeSearch.result, Exception):
            raise FakeSearch.result
        return FakeSearch.result


class TestFind:
    def test_host_of(self):
        assert find.host_of("https://www.a.org/x") == "a.org"
        assert find.host_of(None) is None

    async def test_no_key_keeps_cited_on_own_domain(self):
        conn = FakeConn({"FROM documents": [{"url": "https://a.org/p", "title": "P"},
                                            {"url": "https://other.org/x", "title": "X"}]})
        found, failed = await find.candidates(conn, {"id": 1, "name": "A", "website": "https://www.a.org"},
                                              api_key="")
        assert found == [("https://www.a.org", "the funder's home page"), ("https://a.org/p", "P")]
        assert "no TAVILY_API_KEY" in failed

    async def test_no_website_keeps_every_cited_page(self):
        conn = FakeConn({"FROM documents": [{"url": "https://x.org/p", "title": "P"}]})
        found, failed = await find.candidates(conn, {"id": 1, "name": "A", "website": None}, api_key="k")
        assert found == [("https://x.org/p", "P")] and failed is None

    async def test_search_limited_to_own_domain(self, monkeypatch):
        monkeypatch.setattr(find, "TavilySearch", FakeSearch)
        FakeSearch.result = {"results": [{"url": "https://a.org/grants", "title": None}, {"bad": 1}, "x"]}
        found, failed = await find.candidates(FakeConn(), {"id": 1, "name": "A", "website": "https://a.org"},
                                              api_key="k")
        assert FakeSearch.kw["include_domains"] == ["a.org"]
        assert ("https://a.org/grants", "") in found and failed is None

    @pytest.mark.parametrize("result,expect", [
        ({"error": "quota"}, "failed (quota)"),
        (RuntimeError("down"), "RuntimeError: down"),
    ])
    async def test_search_failure_is_reported(self, monkeypatch, result, expect):
        monkeypatch.setattr(find, "TavilySearch", FakeSearch)
        FakeSearch.result = result
        found, failed = await find.candidates(FakeConn(), {"id": 1, "name": "A", "website": "https://a.org"},
                                              api_key="k")
        assert expect in failed and found == [("https://a.org", "the funder's home page")]


def mock_client(handler):
    def make(**kw):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=kw.get("headers"))
    return make


async def _allowed(url):
    return None


LONG = "<html><body><article>" + "<p>" + "Grant applications are open to NGOs. " * 20 + "</p></article></body></html>"


class TestReadPage:
    async def test_refused_by_access_check(self, monkeypatch):
        async def deny(url):
            return "robots says no"
        monkeypatch.setattr(pull, "check_url", deny)
        assert await pull.read_page("https://a.org") == (None, "robots says no")

    @pytest.mark.parametrize("handler,expect", [
        (lambda r: httpx.Response(404), "answered HTTP 404"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")), "could not be fetched (ConnectError)"),
        (lambda r: (_ for _ in ()).throw(EgressRefused("REFUSED: private")), "REFUSED: private"),
        (lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}), "is a PDF"),
        (lambda r: httpx.Response(200, text="<html>tiny</html>"), "no readable text"),
    ])
    async def test_failures_are_reasons(self, monkeypatch, handler, expect):
        monkeypatch.setattr(pull, "check_url", _allowed)
        monkeypatch.setattr(pull, "guarded_client", mock_client(handler))
        text, why = await pull.read_page("https://a.org/calls")
        assert text is None and expect in why

    async def test_page_text(self, monkeypatch):
        monkeypatch.setattr(pull, "check_url", _allowed)
        monkeypatch.setattr(pull, "guarded_client", mock_client(lambda r: httpx.Response(200, text=LONG)))
        text, why = await pull.read_page("https://a.org/calls")
        assert why is None and "Grant applications" in text

    async def test_feed_items_become_lines(self, monkeypatch):
        rss = ("<rss><channel><title>T</title><item><title>Call A</title><link>https://a.org/1</link>"
               "<description></description></item><item><title>Call B</title></item></channel></rss>")
        monkeypatch.setattr(pull, "check_url", _allowed)
        monkeypatch.setattr(pull, "guarded_client", mock_client(lambda r: httpx.Response(200, text=rss)))
        text, _ = await pull.read_page("https://a.org/feed", feed=True)
        assert text == "title: Call A | link: https://a.org/1\ntitle: Call B"


class TestOutcome:
    def test_lines(self):
        assert pull.Outcome("F", look="x").line() == "F: NEEDS A LOOK. x"
        o = pull.Outcome("F", page="p", written=["a"], passed=["b"], undated=["c"])
        assert o.line() == "F: 1 open written, 1 past deadline (b), 1 with no date (c). Page p"

    def test_match_line(self):
        assert pull.match_line({"added": 2, "orgs": 3, "orgs_without_theme": 1}).startswith("-- 2 new matches for 3")

    def test_deps_from_settings(self, monkeypatch):
        from app.agent import models
        monkeypatch.setattr(models, "resolve_model", lambda name: f"model:{name}")
        s = type("S", (), {"utility_model": "haiku", "tavily_api_key": "k"})()
        assert pull.Deps.from_settings(s) == pull.Deps(model="model:haiku", api_key="k")


FUNDER = {"id": 5, "slug": "acme", "name": "Acme", "website": "https://acme.org", "calls_url": None}


class TestPullOne:
    async def test_nowhere_to_look(self, monkeypatch):
        async def none(conn, f, *, api_key):
            return [], None
        monkeypatch.setattr(pull.find, "candidates", none)
        out = await pull.pull_one(FakePool(FakeConn()), FUNDER, pull.Deps(FakeModel(), ""), pinned=None)
        assert "nowhere to look" in out.look

    async def test_no_calls_page_among_candidates(self, monkeypatch):
        async def some(conn, f, *, api_key):
            return [("https://acme.org", "home")], "no TAVILY_API_KEY"
        monkeypatch.setattr(pull.find, "candidates", some)
        out = await pull.pull_one(FakePool(FakeConn()), FUNDER, pull.Deps(FakeModel({"url": None}), ""),
                                  pinned=None)
        assert out.look == "none of 1 pages on its site looks like a calls page; no TAVILY_API_KEY."

    async def test_unreadable_pinned_page_carries_the_note(self, monkeypatch):
        async def read(url, *, feed=False):
            assert feed is True
            return None, "403."
        monkeypatch.setattr(pull, "read_page", read)
        out = await pull.pull_one(FakePool(FakeConn()), FUNDER, pull.Deps(FakeModel(), ""),
                                  pinned={"url": "https://acme.org/feed", "feed": True, "note": "blocks bots"})
        assert out.page == "https://acme.org/feed" and out.look == "403. Known: blocks bots"

    async def test_sorts_calls_by_deadline_and_writes_open_ones(self, monkeypatch):
        async def read(url, *, feed=False):
            return "page text", None
        written = []

        async def write(conn, funder, call, *, page, text):
            written.append(call.title)
            return "inserted"
        monkeypatch.setattr(pull, "read_page", read)
        monkeypatch.setattr(pull, "_write", write)
        future = (datetime.now(pull.IST).date() + timedelta(days=30)).isoformat()
        model = FakeModel({"calls": [
            {"title": "Open call", "deadline": future},
            {"title": "Old call", "deadline": "2020-01-15"},
            {"title": "Rolling call"},
        ]})
        funder = {**FUNDER, "calls_url": "https://acme.org/calls"}
        out = await pull.pull_one(FakePool(FakeConn()), funder, pull.Deps(model, ""), pinned=None)
        assert written == ["Open call"] and out.written == ["Open call"]
        assert out.passed == ["Old call, 15 Jan 2020"] and out.undated == ["Rolling call"]

    async def test_a_failure_is_a_report_line(self, monkeypatch):
        async def read(url, *, feed=False):
            raise ValueError("boom")
        monkeypatch.setattr(pull, "read_page", read)
        out = await pull.pull_one(FakePool(FakeConn()), {**FUNDER, "calls_url": "u"}, pull.Deps(None, ""),
                                  pinned=None)
        assert out.look == "the pull failed here (ValueError: boom)."


class TestWrite:
    async def test_extra_places_and_tags_are_attached(self, monkeypatch):
        async def resolve(conn, state):
            return ({"Assam": 11, "Goa": 12}.get(state), "unknown")
        seen = {}

        async def write_rfp(conn, rec, funder_id, *, location_id, tag_id, document_id):
            seen.update(rec=rec, location_id=location_id, tag_id=tag_id)
            return "inserted", 99, {}
        monkeypatch.setattr(pull, "resolve_location", resolve)
        monkeypatch.setattr(pull.writer, "write_rfp", write_rfp)
        conn = FakeConn({"FROM tags": [{"id": 1}, {"id": 2}]})
        call = extract.Call(title=" Health call ", states=["Assam", "Mars", "Goa"], themes=["skilling"],
                            domains=["health"])
        status = await pull._write(conn, FUNDER, call, page="https://acme.org/c", text="t")
        assert status == "inserted"
        assert seen["location_id"] == 11 and seen["tag_id"] == 1
        assert seen["rec"].title == "Health call" and seen["rec"].url == "https://acme.org/c"
        inserts = [p for s, p in conn.sql if "INSERT" in s]
        assert inserts[0][:2] == (99, 12) and inserts[1][:2] == (99, 2)
        tag_sql = next(p for s, p in conn.sql if "FROM tags" in s)
        assert tag_sql == (["theme-skilling"], ["health"])

    async def test_no_place_or_tag(self, monkeypatch):
        async def write_rfp(conn, rec, funder_id, *, location_id, tag_id, document_id):
            assert location_id is None and tag_id is None
            return "updated", 1, {}
        monkeypatch.setattr(pull.writer, "write_rfp", write_rfp)
        assert await pull._write(FakeConn(), FUNDER, extract.Call(title="Call"),
                                  page="https://acme.org/c", text="t") == "updated"


class TestRun:
    async def test_report_orders_pinned_first_and_flags_missing(self, monkeypatch):
        monkeypatch.setattr(pull, "PINNED", [{"slug": "pinned-in", "url": "https://p.org", "note": "n"},
                                             {"slug": "pinned-out", "url": "https://q.org", "note": "gone"}])
        funders = [{**FUNDER, "slug": "zeta", "name": "Zeta"}, {**FUNDER, "slug": "pinned-in", "name": "Pin"}]
        conn = FakeConn({"FROM funders": funders, "UPDATE rfps": [{"id": 1}, {"id": 2}]})
        order = []

        async def pull_one(pool, f, deps, *, pinned):
            order.append((f["slug"], bool(pinned)))
            return pull.Outcome(f["name"], page="p", written=["c"] if pinned else [])

        async def flag(pool):
            return {"added": 1, "orgs": 1, "orgs_without_theme": 0}
        monkeypatch.setattr(pull, "pull_one", pull_one)
        monkeypatch.setattr(pull.rfps, "flag_matches", flag)
        report = await pull.run(FakePool(conn), pull.Deps(None, ""), None)
        assert order == [("pinned-in", True), ("zeta", False)]
        assert report[0].startswith("pinned-out: NEEDS A LOOK") and "Known: gone" in report[0]
        assert "2 funders read, 1 open calls written, 2 expired calls closed, 1 need a look." in report[-2]
        assert report[-1].startswith("-- 1 new matches")

    async def test_unknown_slug_is_reported(self, monkeypatch):
        monkeypatch.setattr(pull, "PINNED", [{"slug": "p", "url": "u", "note": "n"}])
        conn = FakeConn()

        async def flag(pool):
            return {"added": 0, "orgs": 0, "orgs_without_theme": 0}
        monkeypatch.setattr(pull.rfps, "flag_matches", flag)
        report = await pull.run(FakePool(conn), pull.Deps(None, ""), ["nobody"])
        assert report[0] == "nobody: no funder in Sangam has this slug; nothing read."
        assert any("slug = ANY" in s for s, _ in conn.sql)


class FakeMakePool:
    def __init__(self):
        self.opened = self.closed = False

    async def open(self):
        self.opened = True

    async def close(self):
        self.closed = True


class TestRunCli:
    async def test_whole_pull_needs_confirmation(self, capsys):
        assert await calls_run.main([], yes=False) == 2
        assert "CONFIRM=1" in capsys.readouterr().out

    async def test_main_prints_report_and_closes(self, monkeypatch, capsys):
        p = FakeMakePool()
        flushed = []
        monkeypatch.setattr(calls_run, "make_pool", lambda url, max_size: p)
        monkeypatch.setattr(calls_run, "configure_langfuse", lambda s: None)
        monkeypatch.setattr(calls_run, "flush_traces", lambda: flushed.append(1))
        monkeypatch.setattr(calls_run.pull.Deps, "from_settings", classmethod(lambda cls, s: cls(None, "")))

        async def run(pool, deps, slugs):
            assert slugs == ["a"]
            return ["line one"]
        monkeypatch.setattr(calls_run.pull, "run", run)
        assert await calls_run.main(["a"], yes=False) == 0
        assert capsys.readouterr().out == "line one\n" and p.closed and flushed

    async def test_match_only(self, monkeypatch, capsys):
        p = FakeMakePool()
        monkeypatch.setattr(calls_run, "make_pool", lambda url, max_size: p)

        async def flag(pool):
            return {"added": 4, "orgs": 2, "orgs_without_theme": 1}
        monkeypatch.setattr(calls_run.rfps, "flag_matches", flag)
        assert await calls_run.match_only() == 0
        assert "4 new matches" in capsys.readouterr().out and p.opened and p.closed
