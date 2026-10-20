"""The research path's tools: search, a page, a document, its pages, and the one save."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.ingest.expectations import concepts_for
from app.ingest.tools import research_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool, running_as
from tests.test_import_roles import MEMBER, STAFF

URL = "https://example.org/csr"
SUMMARY = "Example Foundation funds sports and water projects in Assam."
REAL_CLIENT = research_tools._client


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every URL is allowed unless a test says otherwise, and nothing is archived for real."""
    async def allowed(url):
        return None

    async def upload(bucket, key, data, content_type):
        offline.uploads.append((bucket, key, data, content_type))
        return key

    offline.uploads = []
    monkeypatch.setattr(research_tools, "check_url", allowed)
    monkeypatch.setattr(research_tools.storage, "upload", upload)
    return offline


def web(monkeypatch, handler):
    """The tools' own client, guard and all, over a fake transport."""
    monkeypatch.setattr(research_tools, "_client",
                        lambda original, **kw: REAL_CLIENT(original, transport=httpx.MockTransport(handler), **kw))


class TestCompactJson:
    def test_a_github_listing_is_one_line_per_entry(self):
        listing = json.dumps([{"name": "a.md", "type": "file", "download_url": "https://raw/a.md"},
                              {"name": "dir", "type": "dir", "path": "docs/dir"}])
        assert research_tools._compact_json(listing) == "a.md · file · https://raw/a.md\ndir · dir · docs/dir"

    def test_other_json_and_non_json_pass_through(self):
        assert research_tools._compact_json('{"a": 1}') == '{"a": 1}'
        assert research_tools._compact_json("not json") == "not json"


class TestSearch:
    @pytest.fixture
    def search(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_settings", lambda: SimpleNamespace(tavily_api_key="k"))

        def set_raw(raw, seen=None):
            class Search:
                async def ainvoke(self, payload):
                    if isinstance(raw, Exception):
                        raise raw
                    return raw

            def make(key, max_results):
                if seen is not None:
                    seen.append(max_results)
                return Search()
            monkeypatch.setattr(research_tools, "make_web_search", make)
        return set_raw

    async def test_no_key_says_so(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_settings", lambda: SimpleNamespace(tavily_api_key=""))
        assert (await research_tools.search_public_sources.ainvoke({"query": "x"})).startswith("SEARCH UNAVAILABLE")

    async def test_a_failed_search_is_returned(self, search):
        search(RuntimeError("quota"))
        assert await research_tools.search_public_sources.ainvoke({"query": "x"}) == "search failed: RuntimeError: quota"

    async def test_a_string_answer_is_not_iterated(self, search):
        search({"results": "rate limited"})
        out = await research_tools.search_public_sources.ainvoke({"query": "x"})
        assert out.startswith("search returned str, not results")

    async def test_no_results(self, search):
        search([None, "x"])
        assert (await research_tools.search_public_sources.ainvoke({"query": "x"})).startswith("No results for 'x'")

    async def test_each_hit_is_marked_readable_or_held(self, search, monkeypatch):
        seen = []
        search({"results": [{"url": "https://ok.org/a", "title": "OK"}, {"url": "https://held.org/b"}]}, seen)

        async def check(url):
            return None if "ok.org" in url else "held.org forbids it " * 20
        monkeypatch.setattr(research_tools, "check_url", check)
        out = await research_tools.search_public_sources.ainvoke({"query": "x", "max_results": 50})
        assert seen == [10]
        assert "[READABLE] OK\n  https://ok.org/a" in out and "[HELD] (no title)" in out
        assert "why held: held.org forbids it" in out

    async def test_a_check_that_raises_is_returned(self, search, monkeypatch):
        search({"results": [{"url": "https://ok.org/a"}]})

        async def check(url):
            raise ValueError("bad")
        monkeypatch.setattr(research_tools, "check_url", check)
        out = await research_tools.search_public_sources.ainvoke({"query": "x"})
        assert out == "search_public_sources failed: ValueError: bad"


class TestReadPage:
    async def test_a_refused_url_is_not_fetched(self, monkeypatch):
        async def refuse(url):
            return "robots.txt disallows it"
        monkeypatch.setattr(research_tools, "check_url", refuse)
        web(monkeypatch, lambda r: pytest.fail("fetched"))
        assert await research_tools.read_page.ainvoke({"url": URL}) == "REFUSED: robots.txt disallows it"

    async def test_html_is_extracted_and_archived(self, monkeypatch, offline):
        html = ("<html><head><title>CSR</title></head><body><article><h1>Our CSR</h1>"
                + "<p>Example Foundation spent Rs 4 crore on water projects in Assam in FY2024-25.</p>" * 5
                + "</article></body></html>")
        web(monkeypatch, lambda r: httpx.Response(200, html=html))
        out = await research_tools.read_page.ainvoke({"url": URL})
        assert "Rs 4 crore on water projects" in out
        [(bucket, key, _, ctype)] = offline.uploads
        assert bucket == "source-archive" and key.endswith("example.org-csr.md") and ctype.startswith("text/markdown")

    async def test_json_and_plain_text_are_kept_as_served(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(200, json=[{"name": "a", "type": "file", "path": "p/a"}]))
        assert await research_tools.read_page.ainvoke({"url": URL}) == "a · file · p/a"
        web(monkeypatch, lambda r: httpx.Response(200, text="# Dossier", headers={"content-type": "text/plain"}))
        assert await research_tools.read_page.ainvoke({"url": URL}) == "# Dossier"

    async def test_a_pdf_points_at_fetch_document(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(200, content=b"%PDF-1.4",
                                                  headers={"content-type": "application/pdf"}))
        out = await research_tools.read_page.ainvoke({"url": URL})
        assert "is a PDF (8 bytes). Use fetch_document" in out

    async def test_an_empty_page(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(200, text="   ", headers={"content-type": "text/plain"}))
        assert (await research_tools.read_page.ainvoke({"url": URL})).startswith("No readable text")

    async def test_an_http_error_reads_nothing(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(403))
        assert await research_tools.read_page.ainvoke({"url": URL}) == (
            f"ERROR: {URL} returned HTTP 403. Nothing was read.")

    async def test_a_network_failure(self, monkeypatch):
        def boom(r):
            raise httpx.ConnectError("refused")
        web(monkeypatch, boom)
        assert (await research_tools.read_page.ainvoke({"url": URL})).startswith(f"ERROR: fetching {URL} failed")

    async def test_a_redirect_to_a_held_url_is_refused(self, monkeypatch):
        async def check(url):
            return "held.org is held" if "held.org" in url else None
        monkeypatch.setattr(research_tools, "check_url", check)

        def handler(r):
            if r.url.host == "example.org":
                return httpx.Response(302, headers={"location": "https://held.org/x"})
            pytest.fail("followed the redirect")
        web(monkeypatch, handler)
        out = await research_tools.read_page.ainvoke({"url": URL})
        assert out.startswith(f"REFUSED: {URL} led to https://held.org/x") and "held.org is held" in out

    async def test_a_redirect_off_a_scoped_source_is_refused(self, monkeypatch):
        scoped = SimpleNamespace(path_scoped=True, key="give_do", name="Give.do")
        monkeypatch.setattr(research_tools, "rule_for_url",
                            lambda url: (None, scoped) if "give.do/discover" in url else None)

        def handler(r):
            return httpx.Response(302, headers={"location": "https://give.do/admin"})
        web(monkeypatch, handler)
        out = await research_tools.read_page.ainvoke({"url": "https://give.do/discover/a"})
        assert "off Give.do's allowed paths" in out

    async def test_an_unexpected_failure_is_returned(self, monkeypatch):
        async def boom(url):
            raise RuntimeError("x")
        monkeypatch.setattr(research_tools, "_read_page", boom)
        assert await research_tools.read_page.ainvoke({"url": URL}) == "read_page failed: RuntimeError: x"

    def test_page_name(self):
        assert research_tools.page_name("https://www.axis.org/what-we-do.html?x=1#y") == "axis.org-what-we-do.md"


class TestFetchDocument:
    @pytest.fixture(autouse=True)
    def downloads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research_tools, "downloads_dir", lambda: tmp_path)
        return tmp_path

    async def test_saves_and_archives(self, monkeypatch, downloads, offline):
        web(monkeypatch, lambda r: httpx.Response(200, content=b"%PDF-1.4 body",
                                                  headers={"content-type": "application/pdf"}))
        out = await research_tools.fetch_document.ainvoke({"url": "https://example.org/r/ar.pdf?v=2"})
        assert out == "Saved ar.pdf (13 bytes). Read it with read_document_pages('ar.pdf')."
        assert (downloads / "ar.pdf").read_bytes() == b"%PDF-1.4 body"
        assert offline.uploads[0][3] == "application/pdf"

    async def test_a_refused_url(self, monkeypatch):
        async def refuse(url):
            return "held"
        monkeypatch.setattr(research_tools, "check_url", refuse)
        assert await research_tools.fetch_document.ainvoke({"url": URL}) == "REFUSED: held"

    async def test_too_large_is_dropped(self, monkeypatch, downloads):
        monkeypatch.setattr(research_tools, "MAX_DOWNLOAD_MB", 0)
        web(monkeypatch, lambda r: httpx.Response(200, content=b"x" * 10))
        out = await research_tools.fetch_document.ainvoke({"url": URL, "filename": "big.pdf"})
        assert "larger than the 0 MB limit" in out and not (downloads / "big.pdf").exists()

    async def test_an_http_error(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(500))
        assert (await research_tools.fetch_document.ainvoke({"url": URL})).startswith(f"ERROR: download of {URL}")

    async def test_a_redirect_refusal(self, monkeypatch):
        async def check(url):
            return "held" if "held.org" in url else None
        monkeypatch.setattr(research_tools, "check_url", check)
        web(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://held.org/x"}))
        assert (await research_tools.fetch_document.ainvoke({"url": URL})).startswith("REFUSED:")

    async def test_an_unexpected_failure_is_returned(self, monkeypatch):
        async def boom(url, name):
            raise OSError("disk full")
        monkeypatch.setattr(research_tools, "_fetch_document", boom)
        assert await research_tools.fetch_document.ainvoke({"url": URL}) == "fetch_document failed: OSError: disk full"


class TestReadDocumentPages:
    @pytest.fixture(autouse=True)
    def downloads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research_tools, "downloads_dir", lambda: tmp_path)
        (tmp_path / "ar.pdf").write_bytes(b"%PDF")
        return tmp_path

    def test_a_missing_file_lists_what_is_there(self):
        out = research_tools.read_document_pages.invoke({"filename": "nope.pdf"})
        assert out == "ERROR: nope.pdf is not in the downloads folder. Available: ar.pdf"

    def test_a_malformed_pdf(self, monkeypatch):
        def bad(path, s, e):
            raise ValueError("EOF marker not found")
        monkeypatch.setattr(research_tools, "extract_pdf_text", bad)
        out = research_tools.read_document_pages.invoke({"filename": "ar.pdf"})
        assert out == "ERROR: ar.pdf could not be read as a PDF (ValueError: EOF marker not found)."

    def test_a_scanned_range(self, monkeypatch):
        monkeypatch.setattr(research_tools, "extract_pdf_text", lambda p, s, e: ("", 7))
        assert "has 7 pages but no extractable text" in research_tools.read_document_pages.invoke(
            {"filename": "ar.pdf"})

    def test_text_is_headed_with_the_page_count(self, monkeypatch):
        seen = []

        def extract(path: Path, s, e):
            seen.append((path.name, s, e))
            return "CSR spend", 7
        monkeypatch.setattr(research_tools, "extract_pdf_text", extract)
        out = research_tools.read_document_pages.invoke({"filename": "ar.pdf", "start_page": 2, "end_page": 3})
        assert out == "[ar.pdf: 7 pages]\n\nCSR spend" and seen == [("ar.pdf", 2, 3)]


def spend(**over) -> dict:
    return {"concept": "csr_spend", "fiscal_year": "FY2023-24", "project_name": "Sports scholarships",
            "amount": {"value": 6.74, "unit": "crore", "text": "Rs 6.74 crore"}, "domain": "others",
            "classified_by": "project_name", "confidence": "medium", "source_url": URL,
            "evidence": "The company spent Rs 6.74 crore on sports, reaching 2,400 athletes.", **over}


def research(findings=None, **over) -> dict:
    gaps = [{"concept": c, "reason": "not_stated", "detail": "the annual report does not say"}
            for c in concepts_for("funder")]
    return {"entity_name": "Example Foundation", "entity_kind": "funder", "status": "partial",
            "stopped_reason": "Stopped at the reading limit.", "summary": SUMMARY,
            "findings": [spend()] if findings is None else findings, "gaps": gaps, **over}


class TestSaveResearch:
    @pytest.fixture
    def saving(self, monkeypatch):
        conn = ScriptConn([("SELECT fact_count", None), ("INSERT INTO entity_research", {"id": 31})])
        state = SimpleNamespace(conn=conn, published=[], result=True)
        monkeypatch.setattr(research_tools, "get_pool", lambda: ScriptPool(conn))

        async def rows_for(c, slug):
            return [{"slug": slug}]

        async def publish(history, unplaced):
            state.published.append((history, unplaced))
            return state.result
        monkeypatch.setattr(research_tools, "rows_for", rows_for)
        monkeypatch.setattr(research_tools, "publish", publish)
        return state

    async def save(self, payload, scope=STAFF, **args):
        with running_as(scope):
            return await research_tools.save_research.ainvoke({"findings": payload, **args})

    async def test_a_field_with_neither_finding_nor_gap_is_refused_and_nothing_is_written(self, saving):
        out = await self.save(research(gaps=[]) | {"gaps": []})
        assert out.startswith("REFUSED: a save answers every field with a finding or a gap")
        assert not saving.conn.calls

    async def test_a_save_is_written_published_and_reports_quoted_numbers(self, saving):
        out = await self.save(research())
        assert out.startswith("Saved as entity_research #31 (example-foundation): 1 findings across csr_spend")
        assert "The brief is published" in out and "'2,400' in a csr_spend quote" in out
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert params[3] == "example-foundation" and params[-1] == STAFF.user_id
        assert saving.published[0][0] == [{"slug": "example-foundation"}]

    async def test_an_unpublished_brief_points_at_client_docs(self, saving):
        saving.result = None
        out = await self.save(research(findings=[spend(evidence="The company spent Rs 6.74 crore on sports.")]))
        assert "docs/entities/example-foundation.md on the next `make client-docs`" in out
        assert "only inside quotes" not in out

    async def test_a_brief_that_fails_still_saves(self, saving, monkeypatch):
        async def broken(history, unplaced):
            raise RuntimeError("storage")
        monkeypatch.setattr(research_tools, "publish", broken)
        assert (await self.save(research())).startswith("Saved as entity_research #31")

    async def test_a_fuller_save_today_is_kept_without_replace(self, saving):
        saving.conn.on("SELECT fact_count", {"fact_count": 15, "researched_by": STAFF.user_id})
        out = await self.save(research())
        assert "already has 15 findings saved today" in out
        assert not saving.conn.sql("INSERT")

    async def test_replace_overwrites_and_says_so(self, saving):
        saving.conn.on("SELECT fact_count", {"fact_count": 15, "researched_by": UUID(int=9)})
        out = await self.save(research(), replace=True)
        assert "Replaced 15 findings saved earlier today." in out

    async def test_a_members_own_earlier_save_may_be_replaced(self, saving):
        saving.conn.on("SELECT fact_count", {"fact_count": 0, "researched_by": MEMBER.user_id})
        assert (await self.save(research(), scope=MEMBER)).startswith("Saved as")

    async def test_a_database_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_pool", lambda: BrokenPool())
        out = await self.save(research())
        assert out == "save_research failed: RuntimeError: database down. Report your findings in text."

    async def test_a_staff_sheet_failure_never_quotes_the_error(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_pool", lambda: BrokenPool())
        staff = spend(source_url="https://staff-sources.sangam.invalid/12",
                      evidence="[source:12#FY24!B7] Example Foundation 6.74 crore sports.")
        out = await self.save(research(findings=[staff]))
        assert out.startswith("save_research failed: RuntimeError. Report the failure") and "down" not in out


class TestPublishBrief:
    @pytest.fixture
    def rows(self, monkeypatch):
        def set_rows(rows, published=None):
            conn = ScriptConn([("FROM entity_research", rows)])
            monkeypatch.setattr(research_tools, "get_pool", lambda: ScriptPool(conn))

            async def publish(history):
                slug = history[0]["slug"]
                if isinstance((published or {}).get(slug), Exception):
                    raise published[slug]
                return (published or {}).get(slug, True)
            monkeypatch.setattr(research_tools, "publish", publish)
            return conn
        return set_rows

    async def test_nothing_saved(self, rows):
        rows([])
        out = await self.publish({"slug": "acme"})
        assert out == "No saved research for 'acme'. Research first."

    async def publish(self, args):
        with running_as(STAFF):
            return await research_tools.publish_brief.ainvoke(args)

    async def test_publishes_each_slug_and_names_the_failures(self, rows):
        conn = rows([{"slug": "a"}, {"slug": "a"}, {"slug": "b"}, {"slug": "c"}],
                    {"b": RuntimeError("unreadable")})
        out = await self.publish({})
        assert out == "Published 2 brief(s): a, c. Failed: b."
        assert conn.calls[0][1] == ()

    async def test_storage_unconfigured_publishes_nothing(self, rows):
        rows([{"slug": "a"}], {"a": None})
        assert (await self.publish({"slug": "a"})).startswith("Published nothing of 1. Storage is not configured")

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_pool", lambda: BrokenPool())
        assert await self.publish({}) == "publish_brief failed: RuntimeError: database down"
