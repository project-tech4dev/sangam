"""Supabase Storage: the settings, the bucket migration, and the client.

Every test here runs against httpx.MockTransport rather than a live project,
so what is pinned is our side of the contract: the key we build, that a
failure is a return value and never an exception, and that a disabled client
makes no request at all.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.ingest import brief
from app.ingest.research_records import EntityResearch
from app.ingest.tools import research_tools as research
from app.ingest.writer import ensure_document
from app.integrations import storage

MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0020_storage_buckets.sql"
BUCKETS = ("source-archive", "org-vault")


class TestStorageIsOptional:
    """Both variables or nothing. A half-configured client would fail at the
    first upload, in the middle of a research run, rather than at boot.
    """

    @pytest.mark.parametrize(
        "url,key",
        [("", ""), ("https://x.supabase.co", ""), ("", "service-key")],
    )
    def test_disabled_unless_both_are_set(self, url, key):
        assert Settings(supabase_url=url, supabase_service_key=key).storage_enabled is False

    def test_enabled_when_both_are_set(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_service_key="service-key")
        assert s.storage_enabled is True

    def test_defaults_to_off(self):
        assert Settings().storage_enabled is False


class TestBucketMigration:
    def sql(self) -> str:
        if not MIGRATION.exists():
            pytest.skip("migration not reachable from here")
        return MIGRATION.read_text(encoding="utf-8")

    def test_creates_both_buckets(self):
        sql = self.sql()
        for bucket in BUCKETS:
            assert f"'{bucket}'" in sql, f"{bucket} is not created by the migration"

    def test_both_buckets_are_private(self):
        """A public bucket serves every object to anyone holding the URL, and
        org-vault holds documents governed by a CSO's DPDP consent.
        """
        rows = re.findall(r"\('(?:source-archive|org-vault)',\s*'[^']+',\s*(\w+)", self.sql())
        assert rows, "could not find the bucket VALUES rows — did the INSERT change shape?"
        assert set(rows) == {"false"}, f"a bucket is public: {rows}"

    def test_is_guarded_for_databases_without_a_storage_schema(self):
        """The local Postgres container has no `storage` schema. Unguarded,
        this file breaks `make migrate` for every developer.
        """
        sql = self.sql()
        guard = sql.find("pg_namespace")
        insert = sql.find("INSERT INTO storage.buckets")
        assert guard != -1, "no pg_namespace guard — this will fail on a plain Postgres"
        assert insert != -1, "no INSERT INTO storage.buckets"
        assert guard < insert, "the guard must come before the INSERT"

    def test_is_idempotent(self):
        assert "ON CONFLICT" in self.sql(), "re-running the migration would raise"


# --- the client ------------------------------------------------------------

ENABLED = {"supabase_url": "https://proj.supabase.co", "supabase_service_key": "svc"}


@pytest.fixture
def enabled(monkeypatch):
    """Turn Storage on for one test. get_settings is lru_cached, so the cache
    is what actually has to be replaced, not the environment."""
    monkeypatch.setattr(storage, "get_settings", lambda: Settings(**ENABLED))
    monkeypatch.setattr(storage, "_warned", False)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: Settings())
    monkeypatch.setattr(storage, "_warned", False)


def transport(monkeypatch, handler):
    """Point the client at a MockTransport and record every request."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://proj.supabase.co/storage/v1",
            transport=httpx.MockTransport(record),
        )

    monkeypatch.setattr(storage, "_client", client)
    return seen


class TestArchiveKey:
    def test_two_sources_named_report_pdf_do_not_collide(self):
        """The bug this replaces: _safe_name flattens the URL to its filename,
        so the second report.pdf overwrites the first on disk mid-run.
        """
        a = storage.archive_key("https://a.example/csr/report.pdf", b"one", "report.pdf")
        b = storage.archive_key("https://b.example/csr/report.pdf", b"two", "report.pdf")
        assert a != b
        assert a.endswith("-report.pdf") and b.endswith("-report.pdf")

    def test_same_url_republished_is_a_new_version_not_an_overwrite(self):
        """A funder reissuing csr-report.pdf next year must not replace the
        bytes an existing finding was read from.
        """
        url = "https://x.example/csr-report.pdf"
        assert storage.archive_key(url, b"2024 edition") != storage.archive_key(url, b"2025 edition")

    def test_identical_content_at_one_url_is_one_key(self):
        url = "https://x.example/r.pdf"
        assert storage.archive_key(url, b"same") == storage.archive_key(url, b"same")

    def test_versions_of_one_url_share_a_folder(self):
        url = "https://x.example/r.pdf"
        prefix = storage.url_prefix(url)
        assert storage.archive_key(url, b"a").startswith(f"{prefix}/")
        assert storage.archive_key(url, b"b").startswith(f"{prefix}/")

    def test_content_hash_is_recoverable_from_the_key(self):
        """This is what lets promotion fill documents.content_hash without
        re-downloading the file."""
        key = storage.archive_key("https://x.example/r.pdf", b"bytes", "r.pdf")
        assert storage.hash_from_key(key) == storage.content_hash(b"bytes")
        assert len(storage.hash_from_key(key)) == 64, "every other content_hash is a full sha256"

    def test_a_key_we_did_not_build_yields_no_hash(self):
        assert storage.hash_from_key("prefix/annual-report.pdf") is None


class TestUpload:
    async def test_does_nothing_when_disabled(self, off, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200))
        assert await storage.upload(storage.SOURCE_ARCHIVE, "k", b"x", "application/pdf") is None
        assert seen == [], "a disabled client must not make a request"

    async def test_stores_the_bytes_and_returns_the_key(self, enabled, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200, json={"Key": "k"}))
        assert await storage.upload("source-archive", "ab/cd-r.pdf", b"pdf", "application/pdf") == (
            "ab/cd-r.pdf"
        )
        assert seen[0].url.path == "/storage/v1/object/source-archive/ab/cd-r.pdf"
        assert seen[0].content == b"pdf"
        assert seen[0].headers["x-upsert"] == "false", "an overwrite would destroy provenance"

    async def test_already_archived_counts_as_success(self, enabled, monkeypatch):
        """The object being there is all the caller needs.

        The body is the one the live API actually returns, captured on
        2026-09-30: a duplicate comes back as HTTP **400** with a 409 inside.
        Matching on the transport status alone logged every re-fetch of a
        document as an archiving failure.
        """
        transport(monkeypatch, lambda r: httpx.Response(400, json={
            "statusCode": "409", "error": "Duplicate",
            "message": "The resource already exists", "code": "KeyAlreadyExists",
        }))
        assert await storage.upload("source-archive", "k", b"x", "application/pdf") == "k"

    async def test_a_real_bad_request_is_still_a_failure(self, enabled, monkeypatch):
        """Not every 400 is a duplicate; a malformed key must not look stored."""
        transport(monkeypatch, lambda r: httpx.Response(400, json={
            "statusCode": "400", "error": "InvalidKey", "message": "Invalid key",
        }))
        assert await storage.upload("source-archive", "k", b"x", "application/pdf") is None

    async def test_refuses_a_file_larger_than_the_bucket(self, enabled, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200))
        big = b"x" * (storage.MAX_ARCHIVE_BYTES + 1)
        assert await storage.upload("source-archive", "k", big, "application/pdf") is None
        assert seen == [], "the bytes must not go over the wire to be rejected"

    async def test_a_failure_is_a_None_not_an_exception(self, enabled, monkeypatch):
        """A Storage outage must not abort a research run."""
        transport(monkeypatch, lambda r: httpx.Response(500, text="boom"))
        assert await storage.upload("source-archive", "k", b"x", "application/pdf") is None


class TestArchivedKey:
    async def test_finds_the_newest_version_of_a_url(self, enabled, monkeypatch):
        url = "https://x.example/r.pdf"
        prefix = storage.url_prefix(url)
        seen = transport(
            monkeypatch,
            lambda r: httpx.Response(200, json=[{"name": f"{'be' * 32}-r.pdf"}]),
        )
        assert await storage.archived_key("source-archive", url) == f"{prefix}/{'be' * 32}-r.pdf"
        assert json.loads(seen[0].content)["prefix"] == prefix

    async def test_a_url_that_was_never_archived_is_None(self, enabled, monkeypatch):
        transport(monkeypatch, lambda r: httpx.Response(200, json=[]))
        assert await storage.archived_key("source-archive", "https://x.example/r.pdf") is None

    async def test_storage_being_down_does_not_break_promotion(self, enabled, monkeypatch):
        transport(monkeypatch, lambda r: httpx.Response(503))
        assert await storage.archived_key("source-archive", "https://x.example/r.pdf") is None


class TestSignedUrl:
    async def test_returns_an_absolute_url(self, enabled, monkeypatch):
        transport(
            monkeypatch,
            lambda r: httpx.Response(200, json={"signedURL": "/object/sign/b/k?token=t"}),
        )
        assert await storage.signed_url("b", "k") == (
            "https://proj.supabase.co/storage/v1/object/sign/b/k?token=t"
        )

    async def test_is_None_when_disabled(self, off, monkeypatch):
        transport(monkeypatch, lambda r: httpx.Response(200))
        assert await storage.signed_url("b", "k") is None


# --- the documents row, against a real Postgres ----------------------------

@pytest.mark.integration
class TestEnsureDocumentRecordsTheArchive:
    """The row is what makes the archive findable. A key in the bucket that no
    documents row points at is an orphan.
    """

    def shim(self, url: str):
        return type("Doc", (), {
            "source_url": url, "title": "CSR Report FY2023-24",
            "source_name": "test", "fetched_at": None, "as_of": "FY2023-24",
        })()

    async def test_a_new_row_carries_the_key_and_the_hash(self, db):
        url = "https://test.invalid/test-new-row.pdf"
        doc_id, status = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="csr_report",
            storage_path="ab12cd34ef56/deadbeefcafe-r.pdf", content_hash="deadbeefcafe",
        )
        assert status == "added"
        row = await (await db.execute(
            "SELECT storage_path, content_hash FROM documents WHERE id = %s", (doc_id,)
        )).fetchone()
        assert row["storage_path"] == "ab12cd34ef56/deadbeefcafe-r.pdf"
        assert row["content_hash"] == "deadbeefcafe"

    async def test_backfills_a_row_that_predates_the_archive(self, db):
        """Every documents row created before this feature has a null
        storage_path. Re-promoting has to fill them, not skip them.
        """
        url = "https://test.invalid/test-backfill.pdf"
        first_id, first = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="csr_report"
        )
        assert first == "added"

        second_id, second = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="csr_report",
            storage_path="ab12cd34ef56/feedface1234-r.pdf", content_hash="feedface1234",
        )
        assert (second_id, second) == (first_id, "updated"), "the backfill must reuse the row"
        row = await (await db.execute(
            "SELECT storage_path FROM documents WHERE id = %s", (first_id,)
        )).fetchone()
        assert row["storage_path"] == "ab12cd34ef56/feedface1234-r.pdf"

    async def test_never_overwrites_an_archive_already_recorded(self, db):
        url = "https://test.invalid/test-no-overwrite.pdf"
        doc_id, _ = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="csr_report",
            storage_path="ab/original.pdf", content_hash="original1234",
        )
        _, status = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="csr_report",
            storage_path="ab/different.pdf", content_hash="different123",
        )
        assert status == "matched", "a second promote must not rewrite provenance"
        row = await (await db.execute(
            "SELECT storage_path FROM documents WHERE id = %s", (doc_id,)
        )).fetchone()
        assert row["storage_path"] == "ab/original.pdf"

    async def test_an_unarchived_url_leaves_the_column_null(self, db):
        """A page read with read_page was never downloaded. Claiming a
        storage_path for it would be a lie about provenance.
        """
        url = "https://test.invalid/test-html-page"
        doc_id, _ = await ensure_document(
            db, self.shim(url), funder_id=None, doc_type="webpage"
        )
        row = await (await db.execute(
            "SELECT storage_path, content_hash FROM documents WHERE id = %s", (doc_id,)
        )).fetchone()
        assert row["storage_path"] is None and row["content_hash"] is None


class TestFetchDocumentArchives:
    """The seam between the research tool and the archive.

    Everything above tests the client in isolation; this is the one place that
    asserts fetch_document actually calls it, with the bytes it just wrote.
    """

    @pytest.fixture
    def downloaded(self, monkeypatch, tmp_path):
        """A fetch_document that downloads PDF_BYTES and records what it archived."""
        monkeypatch.setattr(research, "check_url", lambda url: _none())
        monkeypatch.setattr(research, "downloads_dir", lambda: tmp_path)
        monkeypatch.setattr(
            research.httpx, "AsyncClient",
            lambda **kw: _FakeClient(b"%PDF-1.4 annual report", "application/pdf"),
        )
        archived: list[tuple] = []

        async def fake_upload(bucket, key, data, content_type):
            archived.append((bucket, key, data, content_type))
            return key

        monkeypatch.setattr(research.storage, "upload", fake_upload)
        return archived

    async def test_what_was_downloaded_is_what_was_archived(self, downloaded):
        url = "https://funder.example/csr/report.pdf"
        result = await research.fetch_document.ainvoke({"url": url})
        assert "Saved report.pdf" in result

        assert len(downloaded) == 1, "the download was not archived"
        bucket, key, data, content_type = downloaded[0]
        assert bucket == storage.SOURCE_ARCHIVE
        assert data == b"%PDF-1.4 annual report"
        assert content_type == "application/pdf"
        assert key == storage.archive_key(url, data, "report.pdf")

    async def test_a_refused_url_is_never_archived(self, monkeypatch):
        monkeypatch.setattr(research, "check_url", lambda url: _text("held source"))
        called = []
        monkeypatch.setattr(research.storage, "upload", lambda *a: called.append(a))
        result = await research.fetch_document.ainvoke({"url": "https://held.example/x.pdf"})
        assert result.startswith("REFUSED:")
        assert called == [], "the access gate must run before anything is stored"


class _FakeClient:
    """The two-level async context manager httpx.stream() presents."""

    def __init__(self, body: bytes, content_type: str):
        self._body, self._type = body, content_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url):
        return _FakeStream(self._body, self._type)


class _FakeStream:
    def __init__(self, body: bytes, content_type: str):
        self._body, self.headers = body, {"content-type": content_type}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield self._body


async def _none():
    return None


async def _text(value):
    return value


class TestCatalogNaming:
    """The name an object gets once promotion knows whose document it is.

    Two keys exist because they are built at different moments: fetch has only
    a URL and bytes, promotion has a funder and a period.
    """

    def test_reads_as_a_person_would_file_it(self):
        assert storage.catalog_key(
            "terre-des-hommes-deutschland-e-v", "FY2023-24", "tdh_de_jahresbericht_2023.pdf"
        ) == "funders/terre-des-hommes-deutschland-e-v/2023-24-tdh_de_jahresbericht_2023.pdf"

    def test_keeps_the_publishers_own_filename(self):
        """So a row can be matched back to its source by eye, and so a title
        the model wrote cannot drift between runs."""
        key = storage.catalog_key("x", "FY2023", "RNP_AnnualReport24-25.pdf")
        assert key.endswith("RNP_AnnualReport24-25.pdf")

    def test_an_undated_document_keeps_a_clean_name(self):
        assert storage.catalog_key("x", None, "policy.pdf") == "funders/x/policy.pdf"

    def test_a_year_it_cannot_parse_is_left_off_rather_than_guessed(self):
        assert storage.catalog_key("x", "undated", "policy.pdf") == "funders/x/policy.pdf"

    def test_a_collision_is_disambiguated_before_the_extension(self):
        """Same funder, same year, same published filename, different bytes.
        Overwriting one with the other would lose a source."""
        key = storage.catalog_key("x", "FY2023", "report.pdf", suffix="69b46979")
        assert key == "funders/x/2023-report-69b46979.pdf"

    def test_the_fetch_time_name_survives_the_rename(self):
        fetched = storage.archive_key("https://x.example/ar.pdf", b"bytes", "ar.pdf")
        assert storage.filename_from_key(fetched) == "ar.pdf"

    def test_a_name_with_no_hash_is_returned_whole(self):
        assert storage.filename_from_key("funders/x/2023-ar.pdf") == "2023-ar.pdf"


class TestMove:
    async def test_renames_and_reports_success(self, enabled, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200, json={"message": "ok"}))
        assert await storage.move("source-archive", "ab/cd-x.pdf", "funders/y/x.pdf") is True
        body = json.loads(seen[0].content)
        assert body["sourceKey"] == "ab/cd-x.pdf"
        assert body["destinationKey"] == "funders/y/x.pdf"

    async def test_a_failed_move_is_False_not_an_exception(self, enabled, monkeypatch):
        """Promotion must finish: the object is still archived under its
        fetch-time key, and the caller records whichever key is real."""
        transport(monkeypatch, lambda r: httpx.Response(500))
        assert await storage.move("source-archive", "a", "b") is False

    async def test_does_nothing_when_disabled(self, off, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200))
        assert await storage.move("source-archive", "a", "b") is False
        assert seen == []


class TestBriefKey:
    """A brief's key is an identity, not a digest — the same key every time it
    is regenerated, which is why it uploads with replace=True.
    """

    def test_one_key_per_entity(self):
        assert storage.brief_key("sbi-foundation") == "entities/sbi-foundation.md"

    def test_the_key_does_not_change_when_the_brief_does(self):
        assert storage.brief_key("x-foundation") == storage.brief_key("x-foundation")

    async def test_replace_lets_a_regenerated_brief_overwrite(self, enabled, monkeypatch):
        seen = transport(monkeypatch, lambda r: httpx.Response(200, json={"Key": "k"}))
        await storage.upload("source-archive", "entities/x.md", b"# x", "text/markdown",
                             replace=True)
        assert seen[0].headers["x-upsert"] == "true"

    async def test_an_archived_source_still_refuses_to_be_overwritten(self, enabled, monkeypatch):
        """The default has to stay no-overwrite: that is what stops a
        republished report replacing the bytes a finding was read from."""
        seen = transport(monkeypatch, lambda r: httpx.Response(200, json={"Key": "k"}))
        await storage.upload("source-archive", "ab/cd-r.pdf", b"pdf", "application/pdf")
        assert seen[0].headers["x-upsert"] == "false"


BRIEF_ROW = {
    "slug": "acme-foundation", "entity_name": "Acme Foundation", "canonical_name": None,
    "researched_on": "2026-09-30", "status": "complete", "stopped_reason": None,
    "summary": "A foundation.", "website": None, "goals": [], "findings": [],
    "not_found": [], "sources_read": [], "schema_version": 2,
}


class TestBriefRendering:
    """`brief.py` renders; only `render_docs.py` writes repo files. The split is
    what lets a container-run tool publish the same bytes `make client-docs` writes.
    """

    async def test_publishes_under_the_entity_key_and_overwrites(self, monkeypatch):
        """replace=True is the whole point: re-researching an entity has to
        rewrite its brief, not leave the stale one the page links to."""
        sent = []

        async def fake_upload(bucket, key, data, content_type, *, replace=False):
            sent.append((bucket, key, data, content_type, replace))
            return key

        monkeypatch.setattr(brief.storage, "upload", fake_upload)
        assert await brief.publish(dict(BRIEF_ROW)) == "entities/acme-foundation.md"

        bucket, key, data, content_type, replace = sent[0]
        assert (bucket, key) == (storage.SOURCE_ARCHIVE, storage.brief_key("acme-foundation"))
        assert content_type == "text/markdown"
        assert replace is True, "without upsert the brief freezes at its first version"
        assert data == brief.entity_markdown(dict(BRIEF_ROW)).encode("utf-8")

    async def test_says_nothing_happened_when_storage_is_off(self, off):
        assert await brief.publish(dict(BRIEF_ROW)) is None


@pytest.mark.integration
class TestSavingResearchPublishesTheBrief:
    """The bug this closes: the brief existed only after a human ran
    `make client-docs` on the host, so an entity researched in the morning had
    a dead "Research brief" link until someone remembered in the afternoon.
    """

    FINDINGS = EntityResearch(
        entity_name="Testcorp Foundation", entity_kind="funder", status="not_found",
        summary="A foundation that exists only inside this test, and nowhere else.",
    )

    @pytest.fixture
    def saved(self, db, monkeypatch):
        """save_research against the fixture's transaction, recording uploads."""
        monkeypatch.setattr(research, "get_pool", lambda: _PoolOf(db))
        published: list[tuple] = []

        async def fake_upload(bucket, key, data, content_type, *, replace=False):
            published.append((bucket, key, data, replace))
            return key

        monkeypatch.setattr(brief.storage, "upload", fake_upload)
        return published

    async def test_the_brief_is_published_by_the_call_that_saves_it(self, saved):
        result = await research.save_research.ainvoke({"findings": self.FINDINGS})
        assert "Saved as entity_research" in result

        assert len(saved) == 1, "saving research did not publish a brief"
        bucket, key, data, replace = saved[0]
        assert (bucket, key) == (storage.SOURCE_ARCHIVE, "entities/testcorp-foundation.md")
        assert replace is True
        assert b"Testcorp Foundation" in data
        # The exact phrase, not just the word: the Import UI's milestone strip
        # matches /brief is published/i to light "Saved the brief to the
        # bucket". It is the one place the UI reads a tool's prose.
        assert "brief is published" in result

    async def test_the_reply_does_not_claim_publication_that_did_not_happen(self, db, monkeypatch):
        monkeypatch.setattr(research, "get_pool", lambda: _PoolOf(db))
        monkeypatch.setattr(brief.storage, "upload", lambda *a, **k: _none())
        result = await research.save_research.ainvoke({"findings": self.FINDINGS})
        assert "make client-docs" in result and "is published" not in result

    async def test_the_brief_renders_from_the_row_as_stored(self, db, saved):
        """Not from the pydantic object: the row is what `make client-docs`
        renders, and two renderers of one brief would drift."""
        await research.save_research.ainvoke({"findings": self.FINDINGS})
        row = await (await db.execute(
            "SELECT * FROM entity_research WHERE slug = 'testcorp-foundation'"
        )).fetchone()
        assert saved[0][2] == brief.entity_markdown(dict(row)).encode("utf-8")


class _PoolOf:
    """A pool-shaped wrapper around the test's connection, so a tool calling
    get_pool() writes inside the fixture's transaction and is rolled back."""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        conn = self._conn

        @asynccontextmanager
        async def held():
            yield conn

        return held()
