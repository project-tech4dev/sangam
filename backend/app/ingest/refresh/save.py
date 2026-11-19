"""make source-check WRITE=1: archive today's version of each source that differed, then one row per source."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ingest.reading.fetch import archive_document, archive_page
from app.ingest.reading.snapshots import RECORD_SQL
from app.ingest.refresh.compare import Check
from app.ingest.refresh.discover import NEW, Discovery
from app.ingest.refresh.evidence import BROKEN, INTACT, UNANCHORED
from app.ingest.refresh.fetch_status import OK, Today

INSERT_SQL = """
    INSERT INTO source_checks (run_id, slug, url, baseline_snapshot_id, new_snapshot_id, status,
                               findings_intact, findings_broken, findings_unanchored, judge, detail,
                               removed_text, added_text, evidence)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class Saved:
    rows: int
    snapshots: int
    archive_failed: int
    snapshot_ids: dict[str, int] = field(default_factory=dict)  # today's version of each source, by URL


def differed(check: Check) -> bool:
    """Today's version is new to us: fetched, and its fingerprint is not the baseline's."""
    return check.today.status == OK and bool(check.today.fingerprint) and \
        check.today.fingerprint != check.baseline.text_hash


async def archive(url: str, kind: str | None, today: Today) -> str | None:
    """Today's version in the source archive, as the reading tools store it; a document must still be on disk."""
    if kind == "document":
        if today.path is None or not today.path.exists():
            return None
        return await archive_document(url, today.path, mimetypes.guess_type(today.path.name)[0])
    return await archive_page(url, today.text)


async def archive_all(checks: list[Check], found: Discovery) -> dict[str, str | None]:
    """Each source that differed, and each new one, archived before any row is written: a snapshot row never
    names a missing file."""
    keys = {c.baseline.url: await archive(c.baseline.url, c.baseline.kind, c.today) for c in checks if differed(c)}
    for lead, _why in found.new:
        if lead.url in found.fetched:
            keys[lead.url] = await archive(lead.url, lead.kind, found.fetched[lead.url])
    return keys


async def write(conn: Any, run_id: UUID, slug: str, checks: list[Check], found: Discovery,
                keys: dict[str, str | None]) -> Saved:
    """One transaction: a run is saved whole or not at all."""
    ids: dict[str, int] = {}
    failed = 0

    async def snapshot(url: str, kind: str | None, today: Today) -> tuple[int | None, str]:
        nonlocal failed
        if url not in keys:
            return None, ""
        if not keys[url]:
            failed += 1
            return None, "; archive failed"
        row = await (await conn.execute(RECORD_SQL, (url, kind, today.fingerprint, keys[url]))).fetchone()
        ids[url] = row["id"]
        return row["id"], ""

    async with conn.transaction():
        for c in checks:
            new_id, note = await snapshot(c.baseline.url, c.baseline.kind, c.today)
            tally = [sum(v == k for v, _ in c.verdicts) for k in (INTACT, BROKEN, UNANCHORED)]
            detail = f"{c.reason or c.today.reason}{note}"
            await conn.execute(INSERT_SQL, (run_id, slug, c.baseline.url, c.baseline.snapshot_id, new_id, c.status,
                                            *tally, Jsonb(c.judgement) if c.judgement else None, detail or None,
                                            list(c.removed), list(c.added), _evidence(c)))
        for lead, why in found.new:
            today = found.fetched.get(lead.url)
            new_id, note = await snapshot(lead.url, lead.kind, today) if today else (None, "")
            await conn.execute(INSERT_SQL, (run_id, slug, lead.url, None, new_id, NEW, 0, 0, 0, None, f"{why}{note}",
                                            [], [], None))
    return Saved(len(checks) + len(found.new), len(ids), failed, ids)


def _evidence(check: Check) -> Jsonb | None:
    """Each fact's sentence and whether it is still on the page, for the screen to list."""
    return Jsonb([{"verdict": v, "sentence": s} for v, s in check.verdicts]) if check.verdicts else None


def describe(slug: str, run_id: UUID, saved: Saved) -> str:
    failed = f" · {saved.archive_failed} archive failed" if saved.archive_failed else ""
    return (f"{slug}: saved {saved.rows} source_checks rows · {saved.snapshots} new snapshots{failed} "
            f"(run {run_id})")
