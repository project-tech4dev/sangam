"""record_snapshot against a real Postgres with 0058: same text is one row, changed text is a new one."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.ingest.reading import snapshots
from app.ingest.reading.fingerprint import text_hash

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool(monkeypatch):
    try:
        psycopg.connect(DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    async with AsyncConnectionPool(DSN, kwargs={"row_factory": dict_row, "autocommit": True},
                                   min_size=1, max_size=2, open=False) as live:
        monkeypatch.setattr(snapshots, "get_pool", lambda: live)
        url = f"https://test.invalid/{uuid.uuid4()}"
        yield live, url
        async with live.connection() as conn:
            await conn.execute("DELETE FROM source_snapshots WHERE url = %s", (url,))


async def _rows(live, url):
    async with live.connection() as conn:
        return await (await conn.execute(
            "SELECT id, first_seen_at, last_seen_at, archive_key FROM source_snapshots WHERE url = %s ORDER BY id",
            (url,))).fetchall()


async def test_the_same_text_twice_is_one_row(pool):
    live, url = pool
    first = await snapshots.record_snapshot(url, "page", text_hash("Grants of 400 crore"), None)
    again = await snapshots.record_snapshot(url, "page", text_hash("Grants  of 400 crore\n"), "archive/a.md")
    rows = await _rows(live, url)
    assert first == again and len(rows) == 1
    assert rows[0]["last_seen_at"] > rows[0]["first_seen_at"]
    assert rows[0]["archive_key"] == "archive/a.md"


async def test_changed_text_is_a_second_row(pool):
    live, url = pool
    first = await snapshots.record_snapshot(url, "page", text_hash("Grants of 400 crore"), None)
    second = await snapshots.record_snapshot(url, "page", text_hash("Grants of 500 crore"), None)
    assert first != second and len(await _rows(live, url)) == 2
