"""links.archive: a link-only file is fetched once under Import's checks, and its row points at the saved copy."""

from contextlib import asynccontextmanager

import pytest

from app.integrations import storage
from app.proposals import links

URL = "https://give.do/discover/17C4/satra"
KEY = f"{storage.url_prefix(URL)}/{'a' * 64}-give.do-discover-17C4-satra.md"


class FakePool:
    def __init__(self):
        self.sql = []

    @asynccontextmanager
    async def connection(self):
        yield self

    async def execute(self, sql, params=()):
        self.sql.append((sql, params))


@pytest.fixture
def web(monkeypatch):
    calls = {"page": [], "file": []}
    replies = {"page": "SOURCE: give.do\n\nSATRA works in 120 villages.", "file": "Saved ar.pdf (10 bytes).",
               "key": KEY}
    pool = FakePool()

    async def read_page(url):
        calls["page"].append(url)
        return replies["page"]

    async def fetch_document(url, filename):
        calls["file"].append(url)
        return replies["file"]

    async def archived_key(bucket, url):
        assert bucket == storage.SOURCE_ARCHIVE
        return replies["key"]

    monkeypatch.setattr(links.research_tools, "_read_page", read_page)
    monkeypatch.setattr(links.research_tools, "_fetch_document", fetch_document)
    monkeypatch.setattr(links.storage, "archived_key", archived_key)
    monkeypatch.setattr(links, "get_pool", lambda: pool)
    return calls, replies, pool


async def test_a_page_is_fetched_and_its_row_points_at_the_copy(web):
    calls, _, pool = web
    assert await links.archive(207, URL) is None
    assert calls == {"page": [URL], "file": []}
    sql, params = pool.sql[0]
    assert "WHERE id = %s AND storage_path IS NULL" in sql
    assert params == (f"source-archive/{KEY}", "a" * 64, links.EXTRACTOR, 207)


async def test_a_pdf_is_downloaded_instead(web):
    calls, replies, pool = web
    replies["page"] = f"{URL} is a PDF (10 bytes). Use fetch_document to save it, then read_document_pages."
    assert await links.archive(207, URL) is None
    assert calls["file"] == [URL] and len(pool.sql) == 1


@pytest.mark.parametrize("reply, why", [
    (f"ERROR: {URL} returned HTTP 403. Nothing was read.", "the site refused it: HTTP 403"),
    ("REFUSED: robots.txt disallows /discover/", "Sangam may not read that site"),
    (f"No readable text could be extracted from {URL}.", "the page had no text to read"),
    ("ERROR: fetching x failed (ConnectTimeout: timed out).", "the site could not be reached"),
])
async def test_a_refusal_or_error_is_one_short_reason_and_nothing_is_written(web, reply, why):
    _, replies, pool = web
    replies["page"] = reply
    assert await links.archive(207, URL) == why
    assert pool.sql == []


async def test_a_failed_download_is_a_reason(web):
    _, replies, pool = web
    replies["page"] = f"{URL} is a PDF (10 bytes). Use fetch_document to save it."
    replies["file"] = f"ERROR: {URL} is larger than the 50 MB limit."
    assert await links.archive(207, URL) == "it is too large to download"
    assert pool.sql == []


async def test_a_copy_that_was_not_saved(web):
    _, replies, pool = web
    replies["key"] = None
    assert await links.archive(207, URL) == "it was read but could not be saved; try again"
    assert pool.sql == []


async def test_no_web_link(web):
    calls, _, _ = web
    assert await links.archive(207, "") == "it has no web link to fetch"
    assert calls["page"] == []


async def test_an_exception_never_escapes(web, monkeypatch):
    async def boom(url):
        raise RuntimeError("x")

    monkeypatch.setattr(links.research_tools, "_read_page", boom)
    assert await links.archive(207, URL) == "it could not be fetched"
