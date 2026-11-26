"""A version saved research already read is not sent again, and a host that keeps timing out is skipped."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.ingest.reading import fetch, snapshots
from app.ingest.reading.fingerprint import text_hash
from app.ingest.research import draft
from app.ingest.tools import research_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool

URL = "https://example.org/csr"
SAVED = {"id": 21, "archive_key": "aa/csr.md", "researched_on": date(2026, 11, 26)}
SLUG = "hcl-technologies-limited"


async def _none(*_):
    return None


@pytest.fixture(autouse=True)
def _no_slow_hosts():
    fetch._TIMEOUTS.clear()
    yield
    fetch._TIMEOUTS.clear()


class TestSavedReading:
    async def test_outside_a_scout_top_up_nothing_is_looked_up(self, monkeypatch):
        monkeypatch.setattr(snapshots, "get_pool", lambda: pytest.fail("queried"))
        assert await snapshots.saved_reading(URL, "h", SLUG) is None
        with snapshots.collecting():
            assert await snapshots.saved_reading(URL, "h", None) is None

    async def test_a_version_saved_research_read_is_found(self, monkeypatch):
        conn = ScriptConn([("FROM source_snapshots s JOIN entity_research", SAVED)])
        monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
        with snapshots.collecting():
            seen = await snapshots.saved_reading(URL, "h", SLUG)
        assert seen == snapshots.SavedReading("aa/csr.md", date(2026, 11, 26))
        assert conn.calls[0][1] == (URL, "h", SLUG) and "r.slug = %s" in conn.calls[0][0]

    async def test_one_this_run_already_read_is_not(self, monkeypatch):
        conn = ScriptConn([("FROM source_snapshots s JOIN entity_research", SAVED)])
        monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
        with snapshots.collecting() as ids:
            ids.append(21)
            assert await snapshots.saved_reading(URL, "h", SLUG) is None

    async def test_a_failed_lookup_sends_the_page(self, monkeypatch):
        monkeypatch.setattr(snapshots, "get_pool", lambda: BrokenPool())
        with snapshots.collecting():
            assert await snapshots.saved_reading(URL, "h", SLUG) is None


def _serve(monkeypatch, handler):
    real = fetch._client
    monkeypatch.setattr(fetch, "_client", lambda original, **kw: real(
        original, transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def reading(monkeypatch, tmp_path):
    """read_page_text against a served page, a snapshot table holding SAVED for text_hash('Grants'), and no Storage."""
    async def allowed(url):
        return None

    async def upload(bucket, key, data, content_type):
        return "aa/new.md"

    async def record(url, kind, fingerprint, archive_key):
        return 21 if fingerprint == text_hash("Grants") else 22

    conn = ScriptConn([("FROM source_snapshots s JOIN entity_research", SAVED)])
    monkeypatch.setattr(fetch, "check_url", allowed)
    monkeypatch.setattr(fetch, "downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(fetch.storage, "upload", upload)
    monkeypatch.setattr(snapshots, "record_snapshot", record)
    monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
    return conn


class TestReadPage:
    async def test_an_unchanged_version_is_not_sent_and_a_second_read_is(self, monkeypatch, reading):
        _serve(monkeypatch, lambda r: httpx.Response(200, text="Grants", headers={"content-type": "text/plain"}))
        with snapshots.collecting() as ids:
            first = await fetch.read_page_text(URL, SLUG)
            second = await fetch.read_page_text(URL, SLUG)
        assert first.startswith("ALREADY READ") and "26 Nov 2026" in first
        assert "Grants" not in first
        assert second.endswith("Grants") and ids == [21]

    async def test_a_changed_page_is_sent(self, monkeypatch, reading):
        _serve(monkeypatch, lambda r: httpx.Response(200, text="Grants rose", headers={"content-type": "text/plain"}))
        reading.rules = [("FROM source_snapshots s JOIN entity_research", [])]
        with snapshots.collecting() as ids:
            text = await fetch.read_page_text(URL, SLUG)
        assert text.endswith("Grants rose") and ids == [22]

    async def test_another_entitys_researcher_gets_the_text(self, monkeypatch, reading):
        _serve(monkeypatch, lambda r: httpx.Response(200, text="Grants", headers={"content-type": "text/plain"}))
        reading.rules = [("FROM source_snapshots s JOIN entity_research", [])]  # read only under HCL's slug
        with snapshots.collecting():
            text = await fetch.read_page_text(URL, "wipro-foundation")
            first_run = await fetch.read_page_text(URL)
        assert text.endswith("Grants") and first_run.endswith("Grants")
        assert reading.calls[0][1] == (URL, text_hash("Grants"), "wipro-foundation") and len(reading.calls) == 1

    async def test_the_tool_passes_the_drafts_slug_and_works_without_one(self, monkeypatch):
        seen = []

        async def read(url, subject):
            seen.append(subject)
            return "text"

        monkeypatch.setattr(research_tools, "read_page_text", read)
        assert await research_tools.read_page.ainvoke({"url": URL}) == "text"
        with draft.drafting() as current:
            current.slug = SLUG
            await research_tools.read_page.ainvoke({"url": URL})
        assert seen == [None, SLUG]

    async def test_a_document_saved_research_read_says_so(self, monkeypatch, reading):
        _serve(monkeypatch, lambda r: httpx.Response(200, content=b"PK word"))
        monkeypatch.setattr(fetch, "known_fingerprint", lambda key: _value(text_hash("Grants")))
        with snapshots.collecting() as ids:
            reply = await fetch.fetch_document_file(URL, "report.docx", SLUG)
        assert "the version the saved research read on 26 Nov 2026" in reply and ids == [21]


async def _value(v):
    return v


class TestSlowHosts:
    async def test_a_host_that_timed_out_twice_is_not_asked_again(self, monkeypatch, tmp_path):
        asked: list[str] = []

        def stall(request):
            asked.append(str(request.url))
            raise httpx.ReadTimeout("stalled", request=request)

        monkeypatch.setattr(fetch, "check_url", _none)
        monkeypatch.setattr(fetch, "downloads_dir", lambda: tmp_path)
        _serve(monkeypatch, stall)
        nse = "https://nsearchives.nseindia.com/annual/{}.pdf"
        assert "ReadTimeout" in await fetch.fetch_document_file(nse.format(1), None)
        assert "ReadTimeout" in await fetch.read_page_text("https://www.nsearchives.nseindia.com/x")
        reply = await fetch.fetch_document_file(nse.format(3), None)
        assert reply.startswith("ERROR: nsearchives.nseindia.com timed out 2 times") and len(asked) == 2
        assert fetch.slow_host("https://example.org/") is None

    async def test_it_is_forgotten_after_a_day(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(fetch.time, "monotonic", lambda: now[0])
        fetch._TIMEOUTS["nse.in"] = [now[0], now[0]]
        assert fetch.slow_host("https://nse.in/a") == "nse.in"
        now[0] += fetch.SLOW_FOR + 1
        assert fetch.slow_host("https://nse.in/a") is None and "nse.in" not in fetch._TIMEOUTS

    async def test_another_error_is_not_a_strike(self, monkeypatch):
        monkeypatch.setattr(fetch, "check_url", _none)
        _serve(monkeypatch, lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)))
        for _ in range(3):
            assert "ConnectError" in await fetch.read_page_text(URL)
        assert fetch._TIMEOUTS == {}
