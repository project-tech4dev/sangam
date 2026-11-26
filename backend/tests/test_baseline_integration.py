"""The baseline query against a real Postgres with 0058: newest row per URL, wrong_entity skipped."""

from __future__ import annotations

import os
import uuid
from datetime import date

import psycopg
import pytest
from psycopg.rows import dict_row

from app.ingest.refresh import baseline
from app.ingest.research import saved

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():
    try:
        live = await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    slug = f"zz-baseline-{uuid.uuid4().hex[:8]}"
    try:
        async with live.transaction(force_rollback=True):
            yield live, slug
    finally:
        await live.close()


async def snapshot(conn, url: str, text: str) -> int:
    row = await (await conn.execute(
        "INSERT INTO source_snapshots (url, kind, text_hash) VALUES (%s, 'page', %s) RETURNING id",
        (url, text))).fetchone()
    return row["id"]


async def research(conn, slug: str, on: date, ids: list[int] | None, status: str = "complete") -> int:
    row = await (await conn.execute(
        "INSERT INTO entity_research (entity_name, slug, status, summary, researched_on, snapshot_ids) "
        "VALUES ('Zz', %s, %s, 's', %s, %s) RETURNING id", (slug, status, on, ids))).fetchone()
    return row["id"]


async def test_a_narrow_rerun_keeps_the_older_rows_urls(conn):
    db, slug = conn
    about, report = f"https://{slug}.invalid/about", f"https://{slug}.invalid/ar.pdf"
    about_a, report_a, about_b = (await snapshot(db, about, "A"), await snapshot(db, report, "R"),
                                  await snapshot(db, about, "B"))
    await research(db, slug, date(2026, 11, 14), [about_a, report_a])
    newer = await research(db, slug, date(2026, 11, 16), [about_b])
    found, unrecorded = await baseline.load(db, slug)
    by_url = {b.url: b for b in found}
    assert by_url[about].snapshot_id == about_b and by_url[about].research_id == newer
    assert by_url[report].snapshot_id == report_a and unrecorded == 0


async def test_wrong_entity_is_ignored_and_old_rows_are_counted(conn):
    db, slug = conn
    url = f"https://{slug}.invalid/about"
    await research(db, slug, date(2026, 11, 14), [await snapshot(db, url, "A")], status="wrong_entity")
    await research(db, slug, date(2026, 11, 15), None)
    assert await baseline.load(db, slug) == ([], 1)


async def test_saved_research_is_found_by_whole_words(conn):
    db, slug = conn
    word = slug.rsplit("-", 1)[1]  # a short name unique to this test, like "ITC"
    await db.execute("INSERT INTO entity_research (entity_name, canonical_name, slug, status, summary, entity_kind, "
                     "researched_on) VALUES (%s, %s, %s, 'complete', 's', 'funder', %s)",
                     (word, f"{word} Limited", slug, date(2026, 11, 14)))
    assert await saved.latest(db, [f"S{word}h Foundation"], "funder", []) is None
    assert (await saved.latest(db, [f"{word.upper()} Limited, Kolkata"], "funder", [])).slug == slug


async def test_one_slugs_newest_row_is_read_whatever_its_name(conn):
    # A longer name on an older row once won, and gaps the newer top-up filled came back as open.
    db, slug = conn
    for name, on, reason in ((f"{slug} Technologies Limited", date(2026, 11, 14), "not_reached"),
                             (slug, date(2026, 11, 16), "not_stated")):
        await db.execute("INSERT INTO entity_research (entity_name, slug, status, summary, entity_kind, researched_on, "
                         "gaps) VALUES (%s, %s, 'partial', 's', 'funder', %s, %s::jsonb)",
                         (name, slug, on, f'[{{"concept": "rfp", "reason": "{reason}"}}]'))
    found = await saved.latest(db, [slug], "funder", [])
    assert found.researched_on == date(2026, 11, 16) and found.gaps[0]["reason"] == "not_stated"
