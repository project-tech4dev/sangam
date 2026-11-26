"""The research path's tools: search, a page, a document, its pages, and the one save."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest

from app.ingest.catalog.matcher import Match
from app.ingest.reading import fetch, snapshots
from app.ingest.research.expectations import concepts_for
from app.ingest.tools import research_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool, prior_row, running_as, save_in_run
from tests.test_import_roles import ARPAN_STEWARD, KABIL_STEWARD, MEMBER, STAFF

URL = "https://example.org/csr"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUMMARY = "Example Foundation funds sports and water projects in Assam."
REAL_CLIENT = fetch._client


def host(url: str) -> str | None:
    return urlparse(url).hostname


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
    monkeypatch.setattr(fetch, "check_url", allowed)
    monkeypatch.setattr(fetch.storage, "upload", upload)
    return offline


def web(monkeypatch, handler):
    """The tools' own client, guard and all, over a fake transport."""
    monkeypatch.setattr(fetch, "_client",
                        lambda original, **kw: REAL_CLIENT(original, transport=httpx.MockTransport(handler), **kw))


class TestCompactJson:
    def test_a_github_listing_is_one_line_per_entry(self):
        listing = json.dumps([{"name": "a.md", "type": "file", "download_url": "https://raw/a.md"},
                              {"name": "dir", "type": "dir", "path": "docs/dir"}])
        assert fetch._compact_json(listing) == "a.md · file · https://raw/a.md\ndir · dir · docs/dir"

    def test_other_json_and_non_json_pass_through(self):
        assert fetch._compact_json('{"a": 1}') == '{"a": 1}'
        assert fetch._compact_json("not json") == "not json"


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
            return None if host(url) == "ok.org" else "held.org forbids it " * 20
        monkeypatch.setattr(research_tools, "check_url", check)
        out = await research_tools.search_public_sources.ainvoke({"query": "x", "max_results": 50})
        assert seen == [10]
        assert "[READABLE] OK\n  https://ok.org/a" in out and "[HELD] (no title)" in out
        assert "why held: held.org forbids it" in out

    async def test_hits_are_checked_at_once_and_keep_their_order(self, search, monkeypatch):
        search({"results": [{"url": f"https://site{i}.org", "title": f"T{i}"} for i in range(10)]})

        async def check(url):
            await asyncio.sleep(0.2 if host(url) == "site0.org" else 0.1)  # the first finishes last
            return "held" if host(url) == "site3.org" else None
        monkeypatch.setattr(research_tools, "check_url", check)
        started = time.monotonic()
        out = await research_tools.search_public_sources.ainvoke({"query": "x", "max_results": 10})
        assert time.monotonic() - started < 0.6  # in turn it would be 1.1 s
        assert [line for line in out.splitlines() if line.startswith("[")] == [
            f"[{'HELD' if i == 3 else 'READABLE'}] T{i}" for i in range(10)]

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
        monkeypatch.setattr(fetch, "check_url", refuse)
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

    async def test_a_word_file_points_at_fetch_document(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(200, content=b"PK", headers={"content-type": DOCX}))
        assert "is a Word file (2 bytes). Use fetch_document" in await research_tools.read_page.ainvoke({"url": URL})

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
            return "held.org is held" if host(url) == "held.org" else None
        monkeypatch.setattr(fetch, "check_url", check)

        def handler(r):
            if r.url.host == "example.org":
                return httpx.Response(302, headers={"location": "https://held.org/x"})
            pytest.fail("followed the redirect")
        web(monkeypatch, handler)
        out = await research_tools.read_page.ainvoke({"url": URL})
        assert out.startswith(f"REFUSED: {URL} led to https://held.org/x") and "held.org is held" in out

    async def test_a_redirect_off_a_scoped_source_is_refused(self, monkeypatch):
        scoped = SimpleNamespace(path_scoped=True, key="give_do", name="Give.do")
        monkeypatch.setattr(fetch, "rule_for_url",
                            lambda url: (None, scoped) if "give.do/discover" in url else None)

        def handler(r):
            return httpx.Response(302, headers={"location": "https://give.do/admin"})
        web(monkeypatch, handler)
        out = await research_tools.read_page.ainvoke({"url": "https://give.do/discover/a"})
        assert "off Give.do's allowed paths" in out

    async def test_an_unexpected_failure_is_returned(self, monkeypatch):
        async def boom(url):
            raise RuntimeError("x")
        monkeypatch.setattr(research_tools, "read_page_text", boom)
        assert await research_tools.read_page.ainvoke({"url": URL}) == "read_page failed: RuntimeError: x"

    def test_page_name(self):
        assert fetch.page_name("https://www.axis.org/what-we-do.html?x=1#y") == "axis.org-what-we-do.md"


class TestFetchDocument:
    @pytest.fixture(autouse=True)
    def downloads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fetch, "downloads_dir", lambda: tmp_path)
        return tmp_path

    async def test_saves_and_archives(self, monkeypatch, downloads, offline):
        web(monkeypatch, lambda r: httpx.Response(200, content=b"%PDF-1.4 body",
                                                  headers={"content-type": "application/pdf"}))
        out = await research_tools.fetch_document.ainvoke({"url": "https://example.org/r/ar.pdf?v=2"})
        assert out == "Saved ar.pdf (13 bytes). Read it with read_document_pages('ar.pdf')."
        assert (downloads / "ar.pdf").read_bytes() == b"%PDF-1.4 body"
        assert offline.uploads[0][3] == "application/pdf"

    async def test_a_word_file_without_its_extension_gets_one(self, monkeypatch, downloads, offline):
        web(monkeypatch, lambda r: httpx.Response(200, content=b"PK body", headers={"content-type": DOCX}))
        out = await research_tools.fetch_document.ainvoke({"url": "https://example.org/download/form"})
        assert out == "Saved form.docx (7 bytes). Read it with read_document_pages('form.docx')."
        assert (downloads / "form.docx").read_bytes() == b"PK body" and not (downloads / "form").exists()

    async def test_a_refused_url(self, monkeypatch):
        async def refuse(url):
            return "held"
        monkeypatch.setattr(fetch, "check_url", refuse)
        assert await research_tools.fetch_document.ainvoke({"url": URL}) == "REFUSED: held"

    async def test_too_large_is_dropped(self, monkeypatch, downloads):
        monkeypatch.setattr(fetch, "MAX_DOWNLOAD_MB", 0)
        web(monkeypatch, lambda r: httpx.Response(200, content=b"x" * 10))
        out = await research_tools.fetch_document.ainvoke({"url": URL, "filename": "big.pdf"})
        assert "larger than the 0 MB limit" in out and not (downloads / "big.pdf").exists()

    async def test_an_http_error(self, monkeypatch):
        web(monkeypatch, lambda r: httpx.Response(500))
        assert (await research_tools.fetch_document.ainvoke({"url": URL})).startswith(f"ERROR: download of {URL}")

    async def test_a_redirect_refusal(self, monkeypatch):
        async def check(url):
            return "held" if host(url) == "held.org" else None
        monkeypatch.setattr(fetch, "check_url", check)
        web(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://held.org/x"}))
        assert (await research_tools.fetch_document.ainvoke({"url": URL})).startswith("REFUSED:")

    async def test_an_unexpected_failure_is_returned(self, monkeypatch):
        async def boom(url, name):
            raise OSError("disk full")
        monkeypatch.setattr(research_tools, "fetch_document_file", boom)
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

    def test_a_word_file_is_read_by_paragraph(self, downloads):
        from tests.test_cov_pipeline_vault_office_docs import docx_bytes

        (downloads / "form.docx").write_bytes(docx_bytes(["1. Problem statement", "2. Budget"]))
        out = research_tools.read_document_pages.invoke({"filename": "form.docx", "start_page": 2})
        assert out == "[form.docx: 2 paragraphs]\n\n[para 2] 2. Budget"
        assert research_tools.read_document_pages.invoke(
            {"filename": "form.docx", "start_page": 5}) == "form.docx has no text in that range."

    def test_a_damaged_word_file(self, downloads):
        (downloads / "bad.docx").write_bytes(b"not a zip")
        out = research_tools.read_document_pages.invoke({"filename": "bad.docx"})
        assert out.startswith("ERROR: bad.docx could not be read as a Word file (")

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


class TestFindInADocument:
    """A long report is searched for its page numbers before any range is read."""

    PAGES = ["Chairman's letter", "", "Annexure II  Annual Report on CSR Activities", "Form CSR-2 spend: Rs 445.2 crore"]

    @pytest.fixture(autouse=True)
    def downloads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research_tools, "downloads_dir", lambda: tmp_path)
        (tmp_path / "ar.pdf").write_bytes(b"%PDF")
        return tmp_path

    def pages(self, monkeypatch, texts):
        from app.core import extract

        fake = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda t=t: t) for t in texts])
        monkeypatch.setattr(extract, "PdfReader", lambda path: fake)
        extract._pdf_pages.cache_clear()

    def find(self, words, **args):
        return research_tools.read_document_pages.invoke({"filename": "ar.pdf", "find": words, **args})

    def test_it_returns_only_the_pages_that_name_a_word(self, monkeypatch):
        self.pages(monkeypatch, self.PAGES)
        out = self.find("annexure ii|FORM CSR-2", start_page=1, end_page=1)
        assert out.splitlines()[:3] == [
            "[ar.pdf: 4 pages, 2 mention 'annexure ii|FORM CSR-2']",
            "page 3: Annexure II Annual Report on CSR Activities",
            "page 4: Form CSR-2 spend: Rs 445.2 crore",
        ]
        assert "1 of 4 pages have no text (scanned)" in out

    def test_a_snippet_is_cut_around_the_word(self, monkeypatch):
        self.pages(monkeypatch, ["x" * 300 + " CSR obligation " + "y" * 300])
        line = self.find("csr obligation").splitlines()[1]
        assert line.startswith("page 1: …") and line.endswith("…") and "CSR obligation" in line

    def test_no_match_says_so(self, monkeypatch):
        self.pages(monkeypatch, self.PAGES)
        assert self.find("Schedule VII").startswith("No page of ar.pdf (4 pages) mentions 'Schedule VII'.")

    def test_a_scanned_report_is_a_blocked_gap_not_an_absence(self, monkeypatch):
        self.pages(monkeypatch, ["", " "])
        out = self.find("CSR")
        assert "none has text: it is scanned" in out and "'blocked'" in out

    def test_many_matches_are_capped(self, monkeypatch):
        self.pages(monkeypatch, ["CSR"] * (research_tools.FIND_MAX_HITS + 5))
        assert self.find("csr").splitlines()[-2] == "… and 5 more pages; narrow the words to see them."

    def test_a_second_find_in_the_same_file_extracts_nothing_again(self, monkeypatch):
        from app.core import extract

        opened = []
        fake = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "CSR obligation")])
        monkeypatch.setattr(extract, "PdfReader", lambda path: opened.append(path) or fake)
        extract._pdf_pages.cache_clear()
        assert self.find("csr").startswith("[ar.pdf: 1 pages, 1 mention")
        assert self.find("obligation").startswith("[ar.pdf: 1 pages, 1 mention") and len(opened) == 1

    def test_empty_words_are_refused(self):
        assert self.find(" | ").startswith("ERROR: find needs at least one word")

    def test_a_damaged_pdf(self):
        assert self.find("CSR").startswith("ERROR: ar.pdf could not be searched (")

    def test_a_word_file_is_searched_by_paragraph(self, downloads):
        from tests.test_cov_pipeline_vault_office_docs import docx_bytes

        (downloads / "form.docx").write_bytes(docx_bytes(["1. Problem statement", "2. Budget in INR"]))
        out = research_tools.read_document_pages.invoke({"filename": "form.docx", "find": "budget"})
        assert out.splitlines()[:2] == ["[form.docx: 2 paragraphs, 1 mention 'budget']", "paragraph 2: 2. Budget in INR"]


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

    async def save(self, payload, scope=STAFF):
        out, self.run = await save_in_run(payload, scope)
        return out

    def inserted(self, saving) -> list[dict]:
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        return json.loads(params[8])

    async def test_a_field_with_neither_finding_nor_gap_is_refused_and_nothing_is_written(self, saving):
        out = await self.save(research(gaps=[]))
        assert out.startswith("REFUSED, nothing saved: every field gets a finding or a gap")
        assert "Nothing already recorded needs sending again" in out
        # Finishing the contract is the expected loop, not a refusal that moves the run to the strong model.
        assert not saving.conn.sql("INSERT") and self.run.refusals == 0

    async def test_a_whole_save_problem_is_refused_and_counted(self, saving):
        out = await self.save(research(stopped_reason=None))
        assert out.startswith("REFUSED, nothing saved:") and "needs a stopped_reason" in out
        assert self.run.refusals == 1 and self.run.saved is None

    async def test_a_save_is_written_published_and_reports_quoted_numbers(self, saving):
        out = await self.save(research())
        assert out.startswith("Saved as entity_research #31 (example-foundation): 1 findings across csr_spend")
        assert "The brief is published" in out and "'2,400' in a csr_spend quote" in out
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert params[3] == "example-foundation" and params[-1] == STAFF.user_id
        assert saving.published[0][0] == [{"slug": "example-foundation"}]

    async def test_what_was_saved_is_kept_for_the_summary(self, saving):
        await self.save(research(goals=["CSR spend by year"]))
        assert self.run.saved == {"slug": "example-foundation", "entity_kind": "funder", "status": "partial",
                                  "fact_count": 1, "source_count": 1, "concepts_found": ["csr_spend"],
                                  "not_found": sorted(set(concepts_for("funder")) - {"csr_spend"})}
        assert self.run.goals == ["CSR spend by year"]

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

    async def test_a_fuller_save_today_is_merged_not_shrunk(self, saving):
        # c2b6973d step 14: a 57-fact save was refused over the 66 saved that morning, and written again.
        earlier = [spend(project_name=f"Project {i}", evidence=f"The company spent Rs {i} crore on project {i}.")
                   for i in range(1, 16)]
        saving.conn.on("SELECT fact_count", prior_row(earlier, researched_by=STAFF.user_id))
        out = await self.save(research())
        assert out.startswith("Saved as entity_research #31 (example-foundation): 16 findings")
        assert "Merged with the 15 findings saved earlier today." in out and len(self.inserted(saving)) == 16

    async def test_the_same_fact_again_replaces_the_earlier_copy(self, saving):
        saving.conn.on("SELECT fact_count", prior_row([spend(evidence="An older line about Rs 6.74 crore spent.")]))
        await self.save(research())
        [f] = self.inserted(saving)
        assert f["evidence"] == spend()["evidence"]

    async def test_a_refresh_rows_carried_finding_is_kept(self, saving):
        carried = spend(project_name="Kept", evidence="A private line kept by the refresh, unchanged.", carried=True)
        saving.conn.on("SELECT fact_count", prior_row([carried]))
        out = await self.save(research())
        assert out.startswith("Saved as") and any(f.get("carried") for f in self.inserted(saving))

    async def test_gaps_merge_and_a_found_one_closes(self, saving):
        earlier_gap = {"concept": "csr_spend", "fiscal_year": "FY2023-24", "reason": "not_stated",
                       "detail": "the morning's run did not find it"}
        # This run's own gap covers every year, so only a finding can close the morning's.
        kept_gap = {"concept": "csr_spend", "fiscal_year": "FY2022-23", "reason": "blocked", "detail": "403 on the PDF"}
        saving.conn.on("SELECT fact_count", prior_row(gaps=[earlier_gap, kept_gap], snapshot_ids=[1],
                                                      sources_read=["https://example.org/a"]))
        with snapshots.collecting() as ids:
            ids.append(2)
            await self.save(research(sources_read=["https://example.org/b"]))
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        gaps = [(g["concept"], g["fiscal_year"], g["detail"]) for g in json.loads(params[14])]
        assert ("csr_spend", "FY2023-24", "the morning's run did not find it") not in gaps
        assert ("csr_spend", "FY2022-23", "403 on the PDF") in gaps
        assert params[10] == ["https://example.org/a", "https://example.org/b"] and params[16] == [1, 2]

    async def test_a_save_over_a_refresh_row_keeps_its_notes_while_their_facts_stay(self, saving):
        # A refresh set csr_spend to 12 crore over an older 10: the merged row still holds the update, so its note
        # stays, or an older day's 10 crore would compete with it in the brief again.
        updated = spend(project_name="Updated", evidence="It spent Rs 12 crore on the updated project.")
        notes = [{"key": ["csr_spend", "updated", "", "", "", "", "fy2023-24"], "source_url": URL,
                  "evidence": "It spent Rs 10 crore on the updated project.", "updated": True},
                 {"key": ["csr_spend", "gone", "", "", "", "", "fy2023-24"], "source_url": URL,
                  "evidence": "A project that ended.", "updated": True},
                 {"key": ["rfp", "old call"], "source_url": URL, "evidence": "A closed call."}]
        saving.conn.on("SELECT fact_count", prior_row([updated], supersedes=notes))
        await self.save(research())
        [(sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert "supersedes = EXCLUDED.supersedes" in sql
        assert [n["key"][1] for n in json.loads(params[17])] == ["updated", "old call"]

    WRONG = {"findings": [], "status": "wrong_entity", "stopped_reason": "A different trust."}

    async def test_a_wrong_entity_never_erases_todays_right_one(self, saving):
        saving.conn.on("SELECT fact_count", prior_row([spend(project_name="Other")]))
        out = await self.save(research(**self.WRONG))
        assert out.startswith("REFUSED, nothing saved: example-foundation already holds 1 findings")
        assert not saving.conn.sql("INSERT") and self.run.refusals == 0

    async def test_a_wrong_entity_over_an_empty_row_is_saved_alone(self, saving):
        saving.conn.on("SELECT fact_count", prior_row(gaps=[{"concept": "rfp", "reason": "blocked", "detail": "403"}]))
        out = await self.save(research(**self.WRONG))
        assert out.startswith("Saved as") and self.inserted(saving) == []

    async def test_a_wrong_entity_drops_gaps_its_kind_is_not_researched_for(self, saving):
        # An org researcher recorded an rfp gap before finding it was another organisation.
        stray = {"concept": "rfp", "reason": "not_stated", "detail": "no open call"}
        out = await self.save(research(**self.WRONG, gaps=[stray], entity_kind="org"), scope=STAFF)
        assert out.startswith("Saved as")
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert json.loads(params[14]) == []

    async def test_a_wrong_entity_row_is_never_merged_into_the_right_one(self, saving):
        # Its findings are another organisation's: Tata Trust Ltd's CSR figures are not Tata Trusts'.
        other = spend(project_name="Other", evidence="Another company spent Rs 9 crore on its own project.")
        saving.conn.on("SELECT fact_count", prior_row([other], status="wrong_entity"))
        out = await self.save(research())
        assert "Merged" not in out and [f.get("project_name") for f in self.inserted(saving)] == ["Sports scholarships"]

    async def test_a_first_save_drops_a_gap_its_own_finding_fills(self, saving):
        filled = {"concept": "csr_spend", "reason": "blocked", "detail": "the first PDF was a 403",
                  "fiscal_year": spend()["fiscal_year"]}
        await self.save(research(gaps=[*research()["gaps"], filled]))
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert filled["detail"] not in params[14]

    async def test_a_gap_of_the_other_kind_is_dropped_not_refused_for_ever(self, saving):
        # record_findings cannot take a gap back, so one the kind is not researched for must not block every save.
        stray = {"concept": "org_identifier", "reason": "not_stated", "detail": "no registration on the site"}
        saving.conn.on("SELECT fact_count", prior_row(gaps=[stray]))
        out = await self.save(research(gaps=[*research()["gaps"], stray]))
        assert out.startswith("Saved as")
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert "org_identifier" not in params[14]

    async def test_a_run_that_found_nothing_keeps_the_mornings_label(self, saving):
        # The evening's not_found / unknown would hide 1 finding from refresh and promotion.
        saving.conn.on("SELECT fact_count", prior_row([spend(project_name="Morning")]))
        out = await self.save(research(findings=[], status="not_found", entity_kind="unknown", stopped_reason=None))
        assert out.startswith("Saved as"), out
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert (params[2], params[5], params[6]) == ("funder", "partial", "Stopped early.")

    async def test_a_row_of_the_other_kind_is_replaced_not_merged(self, saving):
        # A funder's partner findings carry no tier, so merged into an org they would refuse every save.
        saving.conn.on("SELECT fact_count", prior_row([spend(project_name="Funder")], entity_kind="org"))
        out = await self.save(research())
        assert "Merged" not in out and "replaced the 1 findings saved earlier today as a org" in out
        assert [f["project_name"] for f in self.inserted(saving)] == ["Sports scholarships"]

    async def test_one_object_is_recorded_as_a_list_of_one(self):
        schema = research_tools.record_findings.tool_call_schema.model_json_schema()
        assert any(t.get("type") == "object" for t in schema["properties"]["findings"]["anyOf"])

    async def test_a_members_own_earlier_save_may_be_added_to(self, saving):
        saving.conn.on("SELECT fact_count", prior_row(researched_by=MEMBER.user_id))
        assert (await self.save(research(), scope=MEMBER)).startswith("Saved as")

    async def test_someone_elses_save_today_is_refused(self, saving):
        saving.conn.on("SELECT fact_count", prior_row(researched_by=UUID(int=9)))
        assert (await self.save(research(), scope=MEMBER)).startswith("REFUSED: example-foundation was already")

    async def test_a_cited_page_no_tool_read_is_named(self, saving, monkeypatch):
        async def unfetched(slug, ids, cited):
            return [URL]
        monkeypatch.setattr(snapshots, "log_unfetched", unfetched)
        with snapshots.collecting():
            out = await self.save(research())
        assert f"No tool read these cited pages in this run; check the findings citing them: {URL}." in out

    async def test_outside_a_run_it_says_so(self):
        assert "no research run is open" in await research_tools.save_research.ainvoke(
            {k: v for k, v in research().items() if k not in ("findings", "gaps")})

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

    async def test_a_staff_finding_carried_from_todays_row_never_quotes_the_error(self, saving, monkeypatch):
        carried = spend(source_url="https://staff-sources.sangam.invalid/12", carried=True, project_name="Kept",
                        evidence="[source:12#FY24!B7] Example Foundation 6.74 crore sports.")
        saving.conn.on("SELECT fact_count", prior_row([carried]))
        saving.conn.on("INSERT INTO entity_research", RuntimeError("value 6.74 crore too long"))
        out = await self.save(research())
        assert out.startswith("save_research failed: RuntimeError. Report") and "6.74" not in out

    async def test_the_saved_row_is_kept_for_the_judge(self, saving):
        saving.conn.on("SELECT fact_count", prior_row([spend(project_name="Morning")]))
        await self.save(research())
        assert {f["project_name"] for f in self.run.record["findings"]} == {"Morning", "Sports scholarships"}


def ngo_research(name="Arpan") -> dict:
    gaps = [{"concept": c, "reason": "not_stated", "detail": "the site does not say"} for c in concepts_for("org")]
    return research(findings=[], entity_name=name, entity_kind="org", gaps=gaps)


class TestSaveNgoResearchScope:
    """An NGO's research is saved by its stewards or staff: the brief is keyed on the slug alone."""

    @pytest.fixture
    def saving(self, monkeypatch):
        conn = ScriptConn([("SELECT fact_count", None), ("INSERT INTO entity_research", {"id": 31})])
        state = SimpleNamespace(conn=conn, match=Match("exact", 7), matched=[])
        monkeypatch.setattr(research_tools, "get_pool", lambda: ScriptPool(conn))

        async def rows_for(c, slug):
            return [{"slug": slug}]

        async def publish(history, unplaced):
            return True

        async def org_match(c, row, asking=None):
            state.matched.append(row)
            return state.match
        monkeypatch.setattr(research_tools, "rows_for", rows_for)
        monkeypatch.setattr(research_tools, "publish", publish)
        monkeypatch.setattr(research_tools, "org_match", org_match)
        return state

    async def save(self, scope, payload=None):
        return (await save_in_run(payload or ngo_research(), scope))[0]

    async def test_a_steward_saves_their_own_ngo(self, saving):
        assert (await self.save(ARPAN_STEWARD)).startswith("Saved as entity_research #31 (arpan)")
        assert saving.matched[0]["slug"] == "arpan" and saving.matched[0]["entity_kind"] == "org"

    async def test_a_steward_of_another_ngo_is_refused_and_nothing_is_written(self, saving):
        out = await self.save(KABIL_STEWARD)
        assert out.startswith("REFUSED: researching an NGO is for its stewards")
        assert not saving.conn.sql("INSERT") and not saving.conn.sql("SELECT fact_count")

    async def test_a_slug_held_by_another_ngo_is_refused(self, saving):
        saving.match = Match("none")
        saving.conn.on("FROM orgs WHERE slug", {"id": 7})
        assert (await self.save(KABIL_STEWARD)).startswith("REFUSED")
        assert (await self.save(ARPAN_STEWARD)).startswith("Saved as")

    async def test_a_near_name_alone_does_not_count_as_the_stewards_ngo(self, saving):
        saving.match = Match("trigram", 8)
        assert (await self.save(KABIL_STEWARD)).startswith("REFUSED")

    async def test_a_new_ngo_is_for_staff(self, saving):
        saving.match = Match("none")
        assert (await self.save(ARPAN_STEWARD, ngo_research("Brand New Trust"))).startswith("REFUSED")
        assert (await self.save(STAFF, ngo_research("Brand New Trust"))).startswith("Saved as")
        assert len(saving.matched) == 1

    async def test_a_member_is_refused_before_any_read(self, saving):
        assert (await self.save(MEMBER)).startswith("REFUSED") and not saving.conn.calls


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
