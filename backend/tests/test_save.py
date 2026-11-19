"""Step 17 of the change check: WRITE=1 archives what differed, then saves one row per source."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb

from app.ingest.reading.fetch import Fetched
from app.ingest.refresh import compare, fetch_status, save
from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.compare import CHANGED, MINOR, UNCHANGED
from app.ingest.refresh.discover import Discovery
from app.ingest.refresh.evidence import BROKEN, INTACT, UNANCHORED
from app.ingest.refresh.fetch_status import OK, UNVERIFIED, Today
from tests.cov_ingest_fakes import ScriptConn
from tests.test_change_check import SLUG
from tests.test_diff_evidence import URL, check
from tests.test_discover import RESULTS, Lead

RUN = UUID("00000000-0000-0000-0000-000000000001")
OTHER = "https://funder.example/programmes"


def same() -> save.Check:
    return replace(check(status=UNCHANGED), today=Today(URL, OK, "HTTP 200", text="x", fingerprint="a" * 64))


def blocked() -> save.Check:
    return replace(check(status=UNVERIFIED), today=Today(URL, UNVERIFIED, "HTTP 403"))


class TestDiffered:
    def test_only_a_fetched_version_with_another_fingerprint(self):
        assert save.differed(check(status=CHANGED))
        assert not save.differed(same()) and not save.differed(blocked())
        assert not save.differed(replace(check(), today=Today(URL, OK, "HTTP 200", text="", fingerprint=None)))



async def test_two_reports_with_the_same_filename_each_archive_their_own_file(monkeypatch, tmp_path):
    urls = ["https://funder.example/2023/annual-report.pdf", "https://funder.example/2024/annual-report.pdf"]
    body = {urls[0]: b"%PDF-1.4 report 2023", urls[1]: b"%PDF-1.4 report 2024"}

    async def download(url, filename, directory):
        path = directory / "annual-report.pdf"
        path.write_bytes(body[url])
        return Fetched(url, final_url=url, status=200, content_type="application/pdf", path=path)

    archived: dict[str, bytes] = {}

    async def document(url, path, content_type):
        archived[url] = path.read_bytes()
        return f"key/{len(archived)}.pdf"
    monkeypatch.setattr(fetch_status, "download", download)
    monkeypatch.setattr(save, "archive_document", document)
    baselines = [Baseline(u, n, "document", "0" * 64, None, 31, date(2026, 11, 14)) for n, u in enumerate(urls)]
    today = await fetch_status.fetch_all(baselines, tmp_path)
    await save.archive_all(compare.compare(baselines, today), Discovery())
    assert archived == body

class TestArchive:
    @pytest.fixture
    def stored(self, monkeypatch):
        calls: list[tuple] = []

        async def page(url, text):
            calls.append(("page", url, text))
            return "key/page.md"

        async def document(url, path, content_type):
            calls.append(("document", url, path.name, content_type))
            return "key/report.pdf"
        monkeypatch.setattr(save, "archive_page", page)
        monkeypatch.setattr(save, "archive_document", document)
        return calls

    async def test_a_page_is_archived_by_its_text(self, stored):
        page = check(new="Today's text")
        assert await save.archive(URL, "page", page.today) == "key/page.md"
        assert stored == [("page", URL, "Today's text")]

    async def test_a_document_is_archived_from_the_runs_folder(self, stored, tmp_path):
        path = tmp_path / "report.pdf"
        path.write_bytes(b"%PDF")
        doc = replace(check(kind="document"), today=Today(URL, OK, "HTTP 200", text="t", path=path, fingerprint="b"))
        assert await save.archive(URL, "document", doc.today) == "key/report.pdf"
        assert stored == [("document", URL, "report.pdf", "application/pdf")]

    async def test_a_document_no_longer_on_disk_is_not_archived(self, stored, tmp_path):
        doc = replace(check(kind="document"),
                      today=Today(URL, OK, "HTTP 200", path=tmp_path / "gone.pdf", fingerprint="b"))
        assert await save.archive(URL, "document", doc.today) is None and stored == []

    async def test_only_what_differed_is_archived(self, stored):
        keys = await save.archive_all([same(), blocked(), check(status=CHANGED)], Discovery())
        assert keys == {URL: "key/page.md"} and len(stored) == 1

    async def test_a_new_source_that_was_read_is_archived_too(self, stored):
        lead = Lead.of(RESULTS[2])
        found = Discovery(new=[(lead, "programme"), (Lead.of(RESULTS[3]), "report (unverified: HTTP 403)")],
                          fetched={lead.url: Today(lead.url, OK, "HTTP 200", text="Fellowship", fingerprint="n")})
        assert await save.archive_all([], found) == {lead.url: "key/page.md"}
        assert stored == [("page", lead.url, "Fellowship")]


class TestWrite:
    @staticmethod
    def rows(conn: ScriptConn) -> list[tuple]:
        return [params for _sql, params in conn.sql("INSERT INTO source_checks")]

    async def test_one_row_per_source_and_a_snapshot_for_what_differed(self):
        conn = ScriptConn([("INSERT INTO source_snapshots", {"id": 55})])
        judged = replace(check(status=CHANGED), reason="facts: 1 intact, 1 broken, 1 unanchored",
                         verdicts=((INTACT, "a"), (BROKEN, "b"), (UNANCHORED, "c")),
                         judgement={"meaningful": True})
        unchanged = replace(same(), baseline=replace(same().baseline, url=OTHER, snapshot_id=8))
        saved = await save.write(conn, RUN, SLUG, [judged, unchanged], Discovery(), {URL: "key/page.md"})
        assert saved == save.Saved(rows=2, snapshots=1, archive_failed=0, snapshot_ids={URL: 55})
        [(_sql, snapshot)] = conn.sql("INSERT INTO source_snapshots")
        assert snapshot == (URL, "page", "b" * 64, "key/page.md")
        first, second = self.rows(conn)
        assert first[:9] == (RUN, SLUG, URL, 7, 55, CHANGED, 1, 1, 1)
        assert isinstance(first[9], Jsonb) and first[9].obj == {"meaningful": True}
        assert second == (RUN, SLUG, OTHER, 8, None, UNCHANGED, 0, 0, 0, None, "HTTP 200", [], [], None)
        assert first[13].obj == [{"verdict": INTACT, "sentence": "a"}, {"verdict": BROKEN, "sentence": "b"},
                                 {"verdict": UNANCHORED, "sentence": "c"}]

    async def test_a_failed_archive_records_no_snapshot_and_says_so(self):
        conn = ScriptConn()
        minor = replace(check(status=MINOR), reason="only the order changed")
        saved = await save.write(conn, RUN, SLUG, [minor], Discovery(), {URL: None})
        assert saved.archive_failed == 1 and saved.snapshots == 0 and conn.sql("INSERT INTO source_snapshots") == []
        [row] = self.rows(conn)
        assert row[4] is None and row[10] == "only the order changed; archive failed"

    async def test_an_unverified_source_keeps_its_fetch_reason(self):
        conn = ScriptConn()
        await save.write(conn, RUN, SLUG, [blocked()], Discovery(), {})
        [row] = self.rows(conn)
        assert row[5] == UNVERIFIED and row[10] == "HTTP 403"

    async def test_a_new_source_read_today_gets_its_snapshot(self):
        conn = ScriptConn([("INSERT INTO source_snapshots", {"id": 77})])
        lead = Lead.of(RESULTS[2])
        found = Discovery(new=[(lead, "programme")],
                          fetched={lead.url: Today(lead.url, OK, "HTTP 200", text="t", fingerprint="n" * 64)})
        saved = await save.write(conn, RUN, SLUG, [], found, {lead.url: "key/new.md"})
        assert saved.snapshot_ids == {lead.url: 77}
        [(_sql, snapshot)] = conn.sql("INSERT INTO source_snapshots")
        assert snapshot == (lead.url, "page", "n" * 64, "key/new.md") and self.rows(conn)[0][4] == 77

    async def test_a_new_source_has_no_baseline(self):
        conn = ScriptConn()
        found = Discovery(new=[(Lead.of(RESULTS[2]), "programme: a fellowship")])
        saved = await save.write(conn, RUN, SLUG, [], found, {})
        [row] = self.rows(conn)
        assert saved.rows == 1 and row == (RUN, SLUG, Lead.of(RESULTS[2]).url, None, None, "new", 0, 0, 0, None,
                                           "programme: a fellowship", [], [], None)


def test_describe():
    out = save.describe(SLUG, RUN, save.Saved(rows=5, snapshots=2, archive_failed=1))
    assert out == f"{SLUG}: saved 5 source_checks rows · 2 new snapshots · 1 archive failed (run {RUN})"
