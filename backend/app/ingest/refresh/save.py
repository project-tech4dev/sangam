"""make source-check WRITE=1: archive today's version of each source that differed, then one row per source."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ingest.reading.fetch import archive_document, archive_page
from app.ingest.reading.snapshots import RECORD_SQL
from app.ingest.refresh.compare import Check
from app.ingest.refresh.discover import NEW, Discovery
from app.ingest.refresh.evidence import BROKEN, INTACT, UNANCHORED
from app.ingest.refresh.fetch_status import OK

INSERT_SQL = """
    INSERT INTO source_checks (run_id, slug, url, baseline_snapshot_id, new_snapshot_id, status,
                               findings_intact, findings_broken, findings_unanchored, judge, detail)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class Saved:
    rows: int
    snapshots: int
    archive_failed: int


def differed(check: Check) -> bool:
    """Today's version is new to us: fetched, and its fingerprint is not the baseline's."""
    return check.today.status == OK and bool(check.today.fingerprint) and \
        check.today.fingerprint != check.baseline.text_hash


async def archive(check: Check) -> str | None:
    """Today's version in the source archive, as the reading tools store it; the document must still be on disk."""
    today, kind = check.today, check.baseline.kind
    if kind == "document":
        if today.path is None or not today.path.exists():
            return None
        return await archive_document(check.baseline.url, today.path, mimetypes.guess_type(today.path.name)[0])
    return await archive_page(check.baseline.url, today.text)


async def archive_all(checks: list[Check]) -> dict[str, str | None]:
    """Each source that differed, archived before any row is written: a snapshot row never names a missing file."""
    return {c.baseline.url: await archive(c) for c in checks if differed(c)}


async def write(conn: Any, run_id: UUID, slug: str, checks: list[Check], found: Discovery,
                keys: dict[str, str | None]) -> Saved:
    """One transaction: a run is saved whole or not at all."""
    snapshots = failed = 0
    async with conn.transaction():
        for c in checks:
            new_id, detail = None, c.reason or c.today.reason
            if c.baseline.url in keys:
                key = keys[c.baseline.url]
                if key:
                    row = await (await conn.execute(RECORD_SQL, (c.baseline.url, c.baseline.kind,
                                                                 c.today.fingerprint, key))).fetchone()
                    new_id, snapshots = row["id"], snapshots + 1
                else:
                    detail, failed = f"{detail}; archive failed", failed + 1
            tally = [sum(v == k for v, _ in c.verdicts) for k in (INTACT, BROKEN, UNANCHORED)]
            await conn.execute(INSERT_SQL, (run_id, slug, c.baseline.url, c.baseline.snapshot_id, new_id, c.status,
                                            *tally, Jsonb(c.judgement) if c.judgement else None, detail or None))
        for lead, why in found.new:
            await conn.execute(INSERT_SQL, (run_id, slug, lead.url, None, None, NEW, 0, 0, 0, None, why))
    return Saved(len(checks) + len(found.new), snapshots, failed)


def describe(slug: str, run_id: UUID, saved: Saved) -> str:
    failed = f" · {saved.archive_failed} archive failed" if saved.archive_failed else ""
    return (f"{slug}: saved {saved.rows} source_checks rows · {saved.snapshots} new snapshots{failed} "
            f"(run {run_id})")
