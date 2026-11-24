"""Step 11 of the change check: fetch today's version, and never mistake a failed fetch for a change."""

from __future__ import annotations

import asyncio
import io
from datetime import date
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ingest.reading import fetch
from app.ingest.reading.fetch import Fetched
from app.ingest.reading.fingerprint import text_hash
from app.ingest.refresh import compare, fetch_status
from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.fetch_status import DEAD, OK, UNVERIFIED, classify

URL = "https://funder.example/about"
REAL_CLIENT = fetch._client


def source(url: str = URL, kind: str = "page") -> Baseline:
    return Baseline(url, 7, kind, "h" * 64, "k", 31, date(2026, 11, 14))


class TestClassify:
    @pytest.mark.parametrize("got, status", [
        (Fetched(URL, refused="REFUSED: robots.txt disallows it"), UNVERIFIED),
        (Fetched(URL, status=404), DEAD),
        (Fetched(URL, status=410), DEAD),
        (Fetched(URL, status=403), UNVERIFIED),
        (Fetched(URL, status=429), UNVERIFIED),
        (Fetched(URL, status=503), UNVERIFIED),
        (Fetched(URL, error="ReadTimeout: timed out"), UNVERIFIED),
        (Fetched(URL, status=200, too_large=True), UNVERIFIED),
        (Fetched(URL, final_url="https://funder.example/", status=200), DEAD),
        (Fetched(URL, final_url=URL, status=200, document="PDF"), UNVERIFIED),
        (Fetched(URL, final_url=URL, status=200), UNVERIFIED),
    ])
    def test_each_failure_has_its_status(self, got, status):
        assert classify(got, got.text).status == status

    def test_a_404_on_a_document_download_is_dead(self):
        got = Fetched(URL, status=404, error="HTTPStatusError: Client error '404 Not Found'")
        assert classify(got, "").status == DEAD

    def test_a_page_with_text_is_ok_and_keeps_it(self):
        today = classify(Fetched(URL, final_url=URL + "/", status=200, text="We fund schools."), "We fund schools.")
        assert (today.status, today.text) == (OK, "We fund schools.")

    def test_a_url_that_always_landed_on_the_home_page_is_not_dead_while_it_reads_the_same(self):
        got = Fetched(URL, final_url="https://funder.example/", status=200, text="Welcome")
        assert classify(got, "Welcome", text_hash("Welcome")).status == OK
        assert classify(got, "Welcome", text_hash("Something else")).status == DEAD

    def test_the_home_page_itself_is_not_a_soft_404(self):
        home = "https://funder.example/"
        assert classify(Fetched(home, final_url=home, status=200), "Welcome").status == OK

    def test_a_document_that_now_serves_a_web_page_is_unverified(self, tmp_path):
        got = Fetched(URL, final_url="https://funder.example/login", status=200,
                      content_type="text/html; charset=utf-8", path=tmp_path / "ar-2024.pdf")
        today = classify(got, "")
        assert (today.status, today.reason) == (UNVERIFIED, "now serves a web page, not a document")

    def test_a_scanned_document_is_ok_by_its_file(self, tmp_path):
        got = Fetched(URL, final_url=URL, status=200, path=tmp_path / "scan.pdf")
        assert classify(got, "").status == OK


class TestFetchToday:
    async def test_a_page_is_fetched_as_a_page(self, monkeypatch, tmp_path):
        async def page(url):
            return Fetched(url, final_url=url, status=200, text="Grants")
        monkeypatch.setattr(fetch_status, "fetch_page", page)
        assert (await fetch_status.fetch_today(source(), tmp_path)).text == "Grants"

    async def test_a_document_is_downloaded_into_scratch(self, monkeypatch, tmp_path):
        seen = []

        async def download(url, filename, directory):
            seen.append(directory)
            (directory / "ar.pdf").write_bytes(b"%PDF")
            return Fetched(url, final_url=url, status=200, path=directory / "ar.pdf")
        monkeypatch.setattr(fetch_status, "download", download)
        monkeypatch.setattr(fetch_status, "document_text", lambda path: "Annual report")
        today = await fetch_status.fetch_today(source(kind="document"), tmp_path)
        assert seen[0].parent == tmp_path and (today.status, today.text) == (OK, "Annual report")

    async def test_two_documents_with_the_same_name_keep_their_own_files(self, monkeypatch, tmp_path):
        async def download(url, filename, directory):
            (directory / "annual-report.pdf").write_bytes(url.encode())
            return Fetched(url, final_url=url, status=200, path=directory / "annual-report.pdf")
        monkeypatch.setattr(fetch_status, "download", download)
        monkeypatch.setattr(fetch_status, "document_text", lambda path: "")
        urls = ["https://funder.example/2023/annual-report.pdf", "https://funder.example/2024/annual-report.pdf"]
        today = [await fetch_status.fetch_today(source(u, "document"), tmp_path) for u in urls]
        assert [t.path.read_bytes() for t in today] == [u.encode() for u in urls]

    async def test_a_document_is_fingerprinted_by_the_tools_rule(self, monkeypatch, tmp_path):
        async def download(url, filename, directory):
            (directory / "ar.pdf").write_bytes(b"%PDF long report")
            return Fetched(url, final_url=url, status=200, path=directory / "ar.pdf")
        monkeypatch.setattr(fetch_status, "download", download)
        monkeypatch.setattr(fetch_status, "document_text", lambda path: "Annual report")
        monkeypatch.setattr(fetch_status, "document_hash", lambda path, text: f"tools:{text}")
        today = await fetch_status.fetch_today(source(kind="document"), tmp_path)
        assert today.fingerprint == "tools:Annual report"


    async def test_a_pdf_archived_as_pdf_but_fetched_without_a_suffix_is_unchanged(self, monkeypatch, tmp_path):
        pdf = _pdf("Annual report 2026")
        archived = tmp_path / "annual-report.pdf"
        archived.write_bytes(pdf)
        url = "https://funder.example/download.php?id=3"
        was = Baseline(url, 7, "document", fetch.document_hash(archived), "archive/funder/annual-report.pdf", 31,
                       date(2026, 11, 14))

        async def download(url, filename, directory):
            (directory / "download.php_id_3").write_bytes(pdf)
            return Fetched(url, final_url=url, status=200, content_type="application/pdf",
                           path=directory / "download.php_id_3")
        monkeypatch.setattr(fetch_status, "download", download)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        today = await fetch_status.fetch_today(was, scratch)
        assert [c.status for c in compare.compare([was], [today])] == [compare.UNCHANGED]

    async def test_a_document_url_that_now_serves_html_is_unverified(self, monkeypatch, tmp_path):
        async def download(url, filename, directory):
            (directory / "ar-2024.pdf").write_bytes(b"<html><body>Please log in</body></html>")
            return Fetched(url, final_url="https://funder.example/login", status=200,
                           content_type="text/html; charset=utf-8", path=directory / "ar-2024.pdf")
        monkeypatch.setattr(fetch_status, "download", download)
        today = await fetch_status.fetch_today(source("https://funder.example/reports/ar-2024.pdf", "document"),
                                               tmp_path)
        assert today.status == UNVERIFIED and today.fingerprint is None

    async def test_fetch_all_runs_a_few_at_once_and_keeps_the_order(self, monkeypatch, tmp_path):
        running, peak = 0, 0

        async def fetch_today(source, folder):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return fetch_status.Today(source.url, OK, "HTTP 200")
        monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
        urls = [f"https://funder.example/{n}" for n in range(8)]
        today = await fetch_status.fetch_all([source(u) for u in urls], tmp_path)
        assert [t.url for t in today] == urls
        assert peak == fetch_status.FETCH_AT_ONCE

def _pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class TestFetchingWritesNothing:
    @pytest.fixture(autouse=True)
    def no_writes(self, monkeypatch):
        async def allowed(url):
            return None

        async def refuse(*a):
            pytest.fail("the check must not archive or record")
        monkeypatch.setattr(fetch, "check_url", allowed)
        monkeypatch.setattr(fetch.storage, "upload", refuse)
        monkeypatch.setattr(fetch, "remember", refuse)

    def serve(self, monkeypatch, handler):
        monkeypatch.setattr(fetch, "_client",
                            lambda original, **kw: REAL_CLIENT(original, transport=httpx.MockTransport(handler), **kw))

    async def test_a_page(self, monkeypatch):
        self.serve(monkeypatch, lambda r: httpx.Response(200, text="Grants", headers={"content-type": "text/plain"}))
        got = await fetch.fetch_page(URL)
        assert (got.status, got.text, got.final_url) == (200, "Grants", URL)

    async def test_a_404_page_keeps_its_status(self, monkeypatch):
        self.serve(monkeypatch, lambda r: httpx.Response(404))
        assert (await fetch.fetch_page(URL)).status == 404

    async def test_a_document_lands_in_the_directory_asked(self, monkeypatch, tmp_path):
        self.serve(monkeypatch, lambda r: httpx.Response(200, content=b"%PDF-1.4",
                                                         headers={"content-type": "application/pdf"}))
        got = await fetch.download("https://funder.example/ar.pdf", None, tmp_path)
        assert got.path == tmp_path / "ar.pdf" and got.path.read_bytes() == b"%PDF-1.4"

    async def test_a_gone_document_keeps_its_status(self, monkeypatch, tmp_path):
        self.serve(monkeypatch, lambda r: httpx.Response(410))
        assert (await fetch.download("https://funder.example/ar.pdf", None, tmp_path)).status == 410


def test_describe_counts_and_explains_the_failures():
    today = [fetch_status.Today(URL, OK, "HTTP 200"),
             fetch_status.Today("https://funder.example/old", DEAD, "HTTP 410"),
             fetch_status.Today("https://funder.example/x", UNVERIFIED, "HTTP 403")]
    out = fetch_status.describe("zz", today).splitlines()
    assert out[0] == "zz: fetched 3 · 1 ok · 1 unverified · 1 dead"
    assert out[1] == f"  ok          {URL}" and out[2].endswith("(HTTP 410)") and "dead" in out[2]


def test_document_text_is_empty_for_anything_but_a_pdf(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(b"PK")
    assert fetch.document_text(tmp_path / "a.docx") == ""
