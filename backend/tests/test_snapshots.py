"""record_snapshot: one row per version of a source, and a read never fails because of it."""

from __future__ import annotations

import logging

from app.ingest.reading import snapshots
from app.ingest.reading.fingerprint import text_hash
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool

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


async def test_a_query_error_is_none_too(monkeypatch):
    conn = ScriptConn([("INSERT INTO source_snapshots", RuntimeError("constraint"))])
    monkeypatch.setattr(snapshots, "get_pool", lambda: ScriptPool(conn))
    assert await snapshots.record_snapshot(URL, "document", "abc", None) is None
