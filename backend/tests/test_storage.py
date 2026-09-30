"""Supabase Storage configuration and the bucket migration.

There is no storage client yet — M1 creates the buckets and the settings only.
What is pinned here is the pair of properties that make the rest optional, and
the guard that keeps the migration runnable against a plain Postgres.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import Settings

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
