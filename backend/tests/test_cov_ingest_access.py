"""Whether Import may read a URL: the registry, robots.txt, and the banner a labelled source gets."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.ingest import access
from app.ingest.adapters import _http
from app.ingest.sources import AccessRule
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool


def source(**over) -> SimpleNamespace:
    base = {"name": "Give.do", "host": "give.do", "access_rule": AccessRule.CRAWL_ALLOWED, "basis": "Checked by a person.",
                "path_scoped": False, "dispatchable": True, "path_refusal": lambda url: None, "key": "give_do"}
    return SimpleNamespace(**{**base, **over})


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No DNS, no robots cache carried between tests, and no proposals reaching a database."""
    async def public(url):
        return None

    async def noted(host, url, *, robots_result):
        noted.calls.append((host, url, robots_result))

    noted.calls = []
    monkeypatch.setattr(access, "private_address_refusal", public)
    monkeypatch.setattr(access, "_ROBOTS", {})
    monkeypatch.setattr(access, "_note_proposal", noted)
    monkeypatch.setattr(access, "rule_for_url", lambda url: None)
    serve(monkeypatch, lambda request: pytest.fail(f"network: {request.url}"))
    return noted


def robots(answer: bool | None, monkeypatch):
    async def allows(scheme, host, url):
        return answer
    monkeypatch.setattr(access, "_robots_allows", allows)


class TestCheckUrl:
    async def test_not_http_is_refused(self):
        assert "not an http(s) URL" in await access.check_url("ftp://example.org/a")

    async def test_credentials_in_the_url_are_refused(self):
        assert "user name or password" in await access.check_url("https://me:pw@example.org/")

    async def test_a_private_address_is_refused(self, monkeypatch):
        async def private(url):
            return "10.0.0.1 is private"
        monkeypatch.setattr(access, "private_address_refusal", private)
        assert await access.check_url("https://intranet.example/") == "10.0.0.1 is private"

    async def test_a_check_that_raises_is_a_reason_not_a_raise(self, monkeypatch):
        def broken(url):
            raise ValueError("bad registry")
        monkeypatch.setattr(access, "rule_for_url", broken)
        out = await access.check_url("https://example.org/")
        assert "could not be checked (ValueError: bad registry)" in out

    async def test_a_held_source_is_refused_with_its_basis(self, monkeypatch):
        held = source(dispatchable=False, access_rule=AccessRule.NO_SCRAPING, basis="Terms forbid it.")
        monkeypatch.setattr(access, "rule_for_url", lambda url: (held.access_rule, held))
        out = await access.check_url("https://give.do/x")
        assert "must not be read automatically" in out and "Terms forbid it." in out

    async def test_a_path_scoped_source_refuses_paths_it_does_not_claim(self, monkeypatch):
        scoped = source(path_scoped=True, path_refusal=lambda url: "only /discover/ is open")
        monkeypatch.setattr(access, "rule_for_url", lambda url: (scoped.access_rule, scoped))
        out = await access.check_url("https://give.do/admin")
        assert "only /discover/ is open" in out and "Report this" in out

    async def test_an_unclassified_readable_host_is_noted_as_a_proposal(self, monkeypatch, offline):
        robots(True, monkeypatch)
        assert await access.check_url("https://new.example.org/csr") is None
        assert offline.calls == [("new.example.org", "https://new.example.org/csr", "allowed")]

    async def test_robots_disallow_refuses(self, monkeypatch):
        robots(False, monkeypatch)
        assert "disallows this path" in await access.check_url("https://example.org/private")

    async def test_unreadable_robots_on_an_unknown_host_is_not_permission(self, monkeypatch):
        robots(None, monkeypatch)
        assert "An unknown rule is not permission" in await access.check_url("https://example.org/")

    async def test_unreadable_robots_on_a_checked_host_reads(self, monkeypatch):
        robots(None, monkeypatch)
        known = source()
        monkeypatch.setattr(access, "rule_for_url", lambda url: (known.access_rule, known))
        assert await access.check_url("https://give.do/") is None

    async def test_unreadable_robots_on_a_path_scoped_host_refuses(self, monkeypatch):
        robots(None, monkeypatch)
        scoped = source(path_scoped=True)
        monkeypatch.setattr(access, "rule_for_url", lambda url: (scoped.access_rule, scoped))
        assert "read only on paths robots.txt leaves open" in await access.check_url("https://give.do/discover/a")


def serve(monkeypatch, handler):
    monkeypatch.setattr(access, "guarded_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))


class TestRobots:
    async def test_a_served_file_is_obeyed(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /private\n"))
        assert await access._robots_allows("https", "a.org", "https://a.org/private/x") is False
        assert await access._robots_allows("https", "a.org", "https://a.org/open") is True

    async def test_an_empty_file_allows_everything(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(200, text=""))
        assert await access._robots_allows("https", "b.org", "https://b.org/x") is True

    async def test_a_4xx_means_no_restrictions(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(404))
        assert await access._robots_allows("https", "c.org", "https://c.org/x") is True

    async def test_a_5xx_is_unreadable(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(503))
        assert await access._robots_allows("https", "d.org", "https://d.org/x") is None

    async def test_a_network_failure_is_unreadable(self, monkeypatch):
        def boom(request):
            raise httpx.ConnectError("refused")
        serve(monkeypatch, boom)
        assert await access._robots_allows("https", "e.org", "https://e.org/x") is None

    async def test_robots_is_fetched_once_per_host(self, monkeypatch):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        serve(monkeypatch, handler)
        await access._robots_allows("https", "f.org", "https://f.org/1")
        await access._robots_allows("https", "f.org", "https://f.org/2")
        assert seen == ["https://f.org/robots.txt"]


class TestNoteProposal:
    async def test_the_host_is_normalised_and_upserted(self, monkeypatch):
        import app.db.pool as pool_module
        monkeypatch.undo()  # the autouse fixture stubbed _note_proposal itself
        pool = ScriptPool(ScriptConn())
        monkeypatch.setattr(pool_module, "get_pool", lambda: pool)
        await access._note_proposal("WWW.Example.org", "https://www.example.org/a", robots_result="allowed")
        [(_sql, params)] = pool.conn.sql("INSERT INTO ingest_source_proposals")
        assert params == ("example.org", "https://www.example.org/a", "allowed")
        assert pool.conn.sql("lock_timeout")

    async def test_a_failure_is_swallowed(self, monkeypatch):
        import app.db.pool as pool_module
        monkeypatch.undo()
        monkeypatch.setattr(pool_module, "get_pool", lambda: BrokenPool())
        assert await access._note_proposal("a.org", "https://a.org", robots_result="allowed") is None


class TestBanner:
    def test_no_source_no_banner(self):
        assert access.source_banner("https://example.org") == ""

    @pytest.mark.parametrize(("rule", "phrase"), [
        (AccessRule.MANUAL_AGGREGATOR, "is an aggregator"),
        (AccessRule.INTERNAL_RESEARCH, "the team's earlier research"),
    ])
    def test_a_labelled_source_opens_with_how_to_save_it(self, monkeypatch, rule, phrase):
        monkeypatch.setattr(access, "rule_for_url", lambda url: (rule, source(access_rule=rule)))
        assert phrase in access.source_banner("https://give.do/discover/x")

    def test_a_plain_source_has_no_banner(self, monkeypatch):
        monkeypatch.setattr(access, "rule_for_url", lambda url: (AccessRule.CRAWL_ALLOWED, source()))
        assert access.source_banner("https://give.do/") == ""

    def test_canonical_url_is_httpx_form(self):
        assert access.canonical_url("https://Example.org/a/../b") == "https://example.org/b"


class TestPoliteClient:
    @pytest.fixture(autouse=True)
    def quick(self, monkeypatch):
        monkeypatch.setattr(_http, "POLITE_DELAY_SECONDS", 0)
        monkeypatch.setattr(_http, "BACKOFF_SECONDS", (0.0, 0.0))

    def route(self, monkeypatch, handler):
        real = httpx.AsyncClient
        fake = SimpleNamespace(AsyncClient=lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
                               HTTPError=httpx.HTTPError, URL=httpx.URL)
        monkeypatch.setattr(_http, "httpx", fake)

    async def test_json_is_returned(self, monkeypatch):
        self.route(monkeypatch, lambda r: httpx.Response(200, json={"ok": True}))
        assert await _http.get_json("https://api.example.org/x", {"q": 1}) == {"ok": True}

    async def test_a_rate_limit_backs_off_then_succeeds(self, monkeypatch):
        answers = iter([httpx.Response(429), httpx.Response(200, json=[1])])
        self.route(monkeypatch, lambda r: next(answers))
        assert await _http.get_json("https://api.example.org/x", delay=0) == [1]

    async def test_a_rate_limit_that_never_ends_is_unavailable(self, monkeypatch):
        self.route(monkeypatch, lambda r: httpx.Response(503))
        with pytest.raises(_http.SourceUnavailable, match="did not recover after 2 retries"):
            await _http.get_json("https://api.example.org/x")

    async def test_an_error_status_is_unavailable(self, monkeypatch):
        self.route(monkeypatch, lambda r: httpx.Response(404))
        with pytest.raises(_http.SourceUnavailable, match="HTTP 404"):
            await _http.get_json("https://api.example.org/x")

    async def test_a_non_json_body_is_unavailable(self, monkeypatch):
        self.route(monkeypatch, lambda r: httpx.Response(200, text="<html>"))
        with pytest.raises(_http.SourceUnavailable, match="non-JSON"):
            await _http.get_json("https://api.example.org/x")

    async def test_an_unreachable_host_is_unavailable(self, monkeypatch):
        def boom(request):
            raise httpx.ConnectError("refused")
        self.route(monkeypatch, boom)
        with pytest.raises(_http.SourceUnavailable, match="could not be reached"):
            await _http.get_json("https://api.example.org/x")

    def test_content_hash_is_sha256(self):
        assert _http.content_hash("a") == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
