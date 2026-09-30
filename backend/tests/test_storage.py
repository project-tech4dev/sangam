"""Supabase Storage: the settings, the bucket migration, and the client.

Every test here runs against httpx.MockTransport rather than a live project,
so what is pinned is our side of the contract: the key we build, that a
failure is a return value and never an exception, and that a disabled client
makes no request at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
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
        """409 means the object is there, which is all the caller needs."""
        transport(monkeypatch, lambda r: httpx.Response(409, json={"error": "Duplicate"}))
        assert await storage.upload("source-archive", "k", b"x", "application/pdf") == "k"

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
