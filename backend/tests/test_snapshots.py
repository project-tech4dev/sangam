"""Snapshots: one row per version of a source, collected per researcher, and a read never fails for it."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.ingest.catalog import promote_documents
from app.ingest.middleware import ChosenSources
from app.ingest.reading import fetch, snapshots, staff_sources
from app.ingest.reading.fingerprint import bytes_hash, text_hash
from app.ingest.research.source_guards import PRIVATE_SOURCE_DOMAIN
from app.ingest.tools import research_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool, prior_row, save_in_run
from tests.test_cov_ingest_tools_research import research
from tests.test_import_roles import STAFF
from tests.test_import_sources import _answered

URL = "https://example.org/csr"


async def test_it_returns_the_row_id(monkeypatch):
    conn = ScriptConn([("INSERT INTO source_snapshots", {"id": 7})])
    monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
    assert await snapshots.record_snapshot(URL, "page", text_hash("Grants"), "archive/key.md") == 7
    sql, params = conn.sql("INSERT INTO source_snapshots")[0]
    assert params == (URL, "page", text_hash("Grants"), "archive/key.md")
    assert "ON CONFLICT (url, text_hash) DO UPDATE" in sql and "last_seen_at = now()" in sql


async def test_a_database_error_is_none_not_an_exception(monkeypatch, caplog):
    monkeypatch.setattr(snapshots, "get_pool", lambda: BrokenPool())
    with caplog.at_level(logging.WARNING):
        assert await snapshots.record_snapshot(URL, "page", text_hash("Grants"), None) is None
    assert "record_snapshot failed" in caplog.text


async def test_a_known_fingerprint_is_read_by_archive_key(monkeypatch):
    conn = ScriptConn([("FROM source_snapshots", {"text_hash": "h1"})])
    monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
    assert await snapshots.known_fingerprint("archive/key.pdf") == "h1"
    assert conn.sql("FROM source_snapshots")[0][1] == ("archive/key.pdf",)


async def test_a_failed_fingerprint_lookup_is_none(monkeypatch):
    monkeypatch.setattr(snapshots, "get_pool", lambda: BrokenPool())
    assert await snapshots.known_fingerprint("archive/key.pdf") is None


async def test_promotion_reads_the_version_the_run_read(monkeypatch):
    conn = ScriptConn([("SELECT archive_key FROM source_snapshots", {"archive_key": "aa/read-then.pdf"})])
    assert await snapshots.read_key(conn, [3, 4], URL) == "aa/read-then.pdf"
    assert conn.sql("SELECT archive_key")[0][1] == ([3, 4], URL)
    assert await snapshots.read_key(ScriptConn(), None, URL) is None


async def test_a_url_that_cannot_be_parsed_falls_back_rather_than_failing_the_save():
    conn = ScriptConn()
    assert await snapshots.read_key(conn, [3], "https://example.org:abc/x") is None and conn.calls == []


async def test_a_query_error_is_none_too(monkeypatch):
    conn = ScriptConn([("INSERT INTO source_snapshots", RuntimeError("constraint"))])
    monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
    assert await snapshots.record_snapshot(URL, "document", "abc", None) is None


class TestRemember:
    @pytest.fixture
    def recorded(self, monkeypatch):
        calls: list[tuple] = []
        ids = iter(range(100, 200))

        async def record(url, kind, fingerprint, archive_key):
            calls.append((url, kind, fingerprint, archive_key))
            return next(ids)

        monkeypatch.setattr(snapshots, "record_snapshot", record)
        return calls

    async def test_a_failed_upload_is_not_recorded(self, recorded):
        with snapshots.collecting() as ids:
            await snapshots.remember(URL, "page", "h", None)
        assert recorded == [] and ids == []

    async def test_a_private_source_is_not_recorded(self, recorded):
        vault_url = f"https://org-vault.{PRIVATE_SOURCE_DOMAIN}/documents/5"
        await snapshots.remember(staff_sources.source_url("grants.xlsx"), "document", "h", "k")
        await snapshots.remember(vault_url, "document", "h", "k")
        assert recorded == []

    async def test_the_researcher_collects_each_id_once(self, recorded, monkeypatch):
        monkeypatch.setattr(snapshots, "record_snapshot", lambda *a: _value(7))
        with snapshots.collecting() as ids:
            await snapshots.remember(URL, "page", "h", "k")
            await snapshots.remember(URL, "page", "h", "k")
        assert ids == [7] and snapshots.COLLECTED.get() is None

    async def test_outside_a_researcher_it_still_records(self, recorded):
        await snapshots.remember(URL, "page", "h", "k")
        assert recorded == [(URL, "page", "h", "k")]

    async def test_two_researchers_in_parallel_keep_their_own_ids(self, recorded):
        async def researcher(urls):
            with snapshots.collecting() as ids:
                for url in urls:
                    await snapshots.remember(url, "page", url, "k")
                    await asyncio.sleep(0)
                return ids

        first, second = await asyncio.gather(researcher(["https://a.org/1", "https://a.org/2"]),
                                             researcher(["https://b.org/1"]))
        assert len(first) == 2 and len(second) == 1 and not set(first) & set(second)


async def _value(v):
    return v


class TestTheToolsRecord:
    @pytest.fixture
    def remembered(self, monkeypatch, tmp_path):
        calls: list[tuple] = []

        async def remember(url, kind, fingerprint, archive_key):
            calls.append((url, kind, fingerprint, archive_key))

        async def allowed(url):
            return None

        monkeypatch.setattr(fetch, "remember", remember)
        monkeypatch.setattr(fetch, "known_fingerprint", lambda key: _value(None))
        monkeypatch.setattr(fetch, "check_url", allowed)
        monkeypatch.setattr(fetch, "downloads_dir", lambda: tmp_path)
        return calls

    @staticmethod
    def serve(monkeypatch, response, key):
        real = fetch._client
        monkeypatch.setattr(fetch, "_client", lambda original, **kw: real(
            original, transport=httpx.MockTransport(lambda r: response), **kw))

        async def upload(bucket, k, data, content_type):
            return key

        monkeypatch.setattr(fetch.storage, "upload", upload)

    async def test_a_page_is_recorded_by_its_text_after_it_is_archived(self, monkeypatch, remembered):
        self.serve(monkeypatch, httpx.Response(200, text="Grants  of 400 crore",
                                               headers={"content-type": "text/plain"}), "archive/page.md")
        await fetch.read_page_text(URL)
        assert remembered == [(URL, "page", text_hash("Grants of 400 crore"), "archive/page.md")]

    async def test_a_page_whose_upload_failed_passes_no_key(self, monkeypatch, remembered):
        self.serve(monkeypatch, httpx.Response(200, text="Grants", headers={"content-type": "text/plain"}), None)
        await fetch.read_page_text(URL)
        assert remembered == [(URL, "page", text_hash("Grants"), None)]

    async def test_a_document_is_recorded_by_its_hash(self, monkeypatch, remembered, tmp_path):
        self.serve(monkeypatch, httpx.Response(200, content=b"PK word", headers={"content-type": "application/zip"}),
                   "archive/report.docx")
        await fetch.fetch_document_file(URL, "report.docx")
        assert remembered == [(URL, "document", bytes_hash(b"PK word"), "archive/report.docx")]

    async def test_an_unchanged_document_reuses_its_hash(self, monkeypatch, remembered):
        self.serve(monkeypatch, httpx.Response(200, content=b"%PDF- big report"), "archive/report.pdf")
        monkeypatch.setattr(fetch, "known_fingerprint", lambda key: _value("known-hash"))
        monkeypatch.setattr(fetch, "document_hash", lambda path: pytest.fail("parsed again"))
        await fetch.fetch_document_file(URL, "report.pdf")
        assert remembered == [(URL, "document", "known-hash", "archive/report.pdf")]

    async def test_a_document_whose_upload_failed_is_not_hashed(self, monkeypatch, remembered):
        self.serve(monkeypatch, httpx.Response(200, content=b"PK word"), None)
        monkeypatch.setattr(fetch, "document_hash", lambda path: pytest.fail("hashed"))
        await fetch.fetch_document_file(URL, "report.docx")
        assert remembered == []


class TestEachSubagentGetsItsOwnList:
    async def test_two_launches_in_parallel(self, monkeypatch):
        monkeypatch.setattr(snapshots, "record_snapshot", lambda url, *a: _value(hash(url) % 1000))

        def task(call_id):
            return SimpleNamespace(tool_call={"name": "task", "args": {}, "id": call_id},
                                   state={"messages": _answered({"web": True})})

        def researcher(urls):
            async def handler(request):
                for url in urls:
                    await snapshots.remember(url, "page", "h", "k")
                    await asyncio.sleep(0)
                return list(snapshots.COLLECTED.get())
            return handler

        a, b = await asyncio.gather(
            ChosenSources().awrap_tool_call(task("a"), researcher(["https://a.org/1", "https://a.org/2"])),
            ChosenSources().awrap_tool_call(task("b"), researcher(["https://b.org/1"])))
        assert len(a) == 2 and len(b) == 1 and snapshots.COLLECTED.get() is None

    async def test_other_tools_get_no_list(self):
        async def handler(request):
            return snapshots.COLLECTED.get()

        request = SimpleNamespace(tool_call={"name": "read_page", "args": {}, "id": "r"}, state={})
        assert await ChosenSources().awrap_tool_call(request, handler) is None


class TestTheSaveLinksWhatWasRead:
    @pytest.fixture
    def saving(self, monkeypatch):
        conn = ScriptConn([("SELECT fact_count", None), ("INSERT INTO entity_research", {"id": 31})])
        logged: list[tuple] = []
        monkeypatch.setattr(research_tools, "get_pool", lambda: ScriptPool(conn))
        monkeypatch.setattr(research_tools, "rows_for", lambda c, slug: _value([{"slug": slug}]))
        monkeypatch.setattr(research_tools, "publish", lambda history, unplaced: _value(True))

        async def log_unfetched(slug, ids, cited):
            logged.append((slug, ids, cited))
            return []
        monkeypatch.setattr(snapshots, "log_unfetched", log_unfetched)
        return SimpleNamespace(conn=conn, logged=logged)

    async def save(self):
        reply, _ = await save_in_run(research(), STAFF)
        return reply

    async def test_a_researchers_ids_are_saved_with_its_findings(self, saving):
        with snapshots.collecting() as ids:
            ids.extend([3, 4])
            assert (await self.save()).startswith("Saved as entity_research #31")
        [(sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert params[-2] == [3, 4] and "snapshot_ids = EXCLUDED.snapshot_ids" in sql
        assert saving.logged == [("example-foundation", [3, 4], [URL])]

    async def test_outside_a_researcher_nothing_is_claimed(self, saving):
        await self.save()
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert params[-2] is None and saving.logged == []

    async def test_a_second_save_today_keeps_the_first_ones_ids(self, saving):
        saving.conn.on("SELECT fact_count", prior_row(snapshot_ids=[1, 3]))
        with snapshots.collecting() as ids:
            ids.extend([3, 4])
            await self.save()
        [(_sql, params)] = saving.conn.sql("INSERT INTO entity_research")
        assert params[-2] == [1, 3, 4]


class TestLogUnfetched:
    async def test_a_cited_url_no_tool_fetched_is_logged(self, monkeypatch, caplog):
        conn = ScriptConn([("FROM source_snapshots", [{"id": 3, "url": URL}])])
        monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
        with caplog.at_level(logging.INFO):
            await snapshots.log_unfetched("x", [3], [URL, "https://example.org/other"])
        assert "cites https://example.org/other" in caplog.text and f"cites {URL}," not in caplog.text

    async def test_a_private_source_is_never_looked_up(self, monkeypatch):
        monkeypatch.setattr(snapshots, "get_pool", lambda: pytest.fail("queried"))
        await snapshots.log_unfetched("x", [], [staff_sources.source_url("grants.xlsx")])

    async def test_an_unparseable_url_is_skipped_not_raised(self, monkeypatch, caplog):
        conn = ScriptConn([("FROM source_snapshots", [{"id": 3, "url": URL}])])
        monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
        with caplog.at_level(logging.INFO):
            await snapshots.log_unfetched("x", [3], ["https://example.org:abc/x", "https://example.org/other"])
        assert "not a URL that can be fetched" in caplog.text and "cites https://example.org/other" in caplog.text

    async def test_a_database_error_does_not_raise(self, monkeypatch, caplog):
        monkeypatch.setattr(snapshots, "get_pool", lambda: BrokenPool())
        with caplog.at_level(logging.WARNING):
            await snapshots.log_unfetched("x", [3], [URL])
        assert "snapshots for x not checked" in caplog.text


class TestAMovedFileKeepsItsSnapshot:
    KEY = f"{'a' * 8}/{'a' * 64}-report.pdf"

    @pytest.fixture
    def shelf(self, monkeypatch):
        state = SimpleNamespace(move_ok=True)
        monkeypatch.setattr(promote_documents.storage, "stat", lambda bucket, key: _value(None))
        monkeypatch.setattr(promote_documents.storage, "move", lambda bucket, src, dst: _value(state.move_ok))
        monkeypatch.setattr(snapshots, "get_pool", lambda: pytest.fail("shelving took a second connection"))
        return state

    async def test_the_key_follows_the_file_without_a_second_connection(self, shelf):
        with snapshots.recording_moves() as moves:
            destination = await promote_documents._shelve(self.KEY, "zz-ltd", "FY2023-24", "a" * 64)
        assert destination != self.KEY and moves == [(self.KEY, destination)]

    async def test_a_failed_move_changes_nothing(self, shelf):
        shelf.move_ok = False
        with snapshots.recording_moves() as moves:
            assert await promote_documents._shelve(self.KEY, "zz-ltd", "FY2023-24", "a" * 64) == self.KEY
        assert moves == []

    async def test_moved_updates_each_row(self, monkeypatch):
        conn = ScriptConn()
        monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
        await snapshots.moved([("old/a.pdf", "funders/x/a.pdf"), ("old/b.pdf", "funders/x/b.pdf")])
        assert [params for _sql, params in conn.sql("UPDATE source_snapshots")] == [
            ("funders/x/a.pdf", "old/a.pdf"), ("funders/x/b.pdf", "old/b.pdf")]

    async def test_nothing_moved_takes_no_connection(self, monkeypatch):
        monkeypatch.setattr(snapshots, "get_pool", lambda: pytest.fail("queried"))
        await snapshots.moved([])

    async def test_a_failed_update_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(snapshots, "get_pool", lambda: BrokenPool())
        await snapshots.moved([("old/key.pdf", "funders/x/key.pdf")])
