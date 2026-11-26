"""The versions of each page and report Scout read, kept so a later check can tell what changed."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.db.pool import get_pool
from app.ingest.reading import staff_sources, vault
from app.ingest.reading.access import canonical_url

logger = logging.getLogger(__name__)

# One row per version: re-reading an unchanged source bumps last_seen_at, and keeps the first archived copy.
RECORD_SQL = """
    INSERT INTO source_snapshots (url, kind, text_hash, archive_key)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (url, text_hash) DO UPDATE SET
        last_seen_at = now(),
        archive_key = COALESCE(source_snapshots.archive_key, EXCLUDED.archive_key)
    RETURNING id
"""

# The snapshot ids one researcher read; ChosenSources gives each launched subagent its own list.
COLLECTED: ContextVar[list[int] | None] = ContextVar("import_snapshot_ids", default=None)


@contextmanager
def collecting() -> Iterator[list[int]]:
    ids: list[int] = []
    token = COLLECTED.set(ids)
    try:
        yield ids
    finally:
        COLLECTED.reset(token)


async def remember(url: str, kind: str, fingerprint: str, archive_key: str | None) -> None:
    """Record what a tool just archived and add it to this researcher's list.
    Nothing without an archived copy (file first, then row), and nothing private."""
    if not archive_key or staff_sources.is_staff_source_url(url) or vault.is_vault_url(url):
        return
    snapshot_id = await record_snapshot(url, kind, fingerprint, archive_key)
    ids = COLLECTED.get()
    if snapshot_id is not None and ids is not None and snapshot_id not in ids:
        ids.append(snapshot_id)


async def known_fingerprint(archive_key: str) -> str | None:
    """The fingerprint already recorded for these exact bytes; None when there is none or the lookup failed."""
    try:
        async with get_pool().connection() as conn:
            row = await (await conn.execute(
                "SELECT text_hash FROM source_snapshots WHERE archive_key = %s LIMIT 1", (archive_key,))).fetchone()
        return row["text_hash"] if row else None
    except Exception:
        logger.warning("snapshot lookup failed for %s", archive_key, exc_info=True)
        return None


async def read_key(conn: Any, snapshot_ids: list[int] | None, url: str) -> str | None:
    """The archived copy of url this research run read, not a newer one a change check archived since."""
    if not snapshot_ids:
        return None
    row = await (await conn.execute(
        "SELECT archive_key FROM source_snapshots WHERE id = ANY(%s) AND url = %s AND archive_key IS NOT NULL "
        "ORDER BY last_seen_at DESC LIMIT 1", (snapshot_ids, canonical_url(url)))).fetchone()
    return row["archive_key"] if row else None


async def record_snapshot(url: str, kind: str, fingerprint: str, archive_key: str | None) -> int | None:
    """The id of this version of url, from text_hash or document_hash; an unchanged re-read bumps last_seen_at.
    Never raises: a read must not fail because its bookkeeping did."""
    try:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(RECORD_SQL, (url, kind, fingerprint, archive_key))
            ).fetchone()
        return row["id"] if row else None
    except Exception:
        logger.warning("record_snapshot failed for %s", url, exc_info=True)
        return None


MOVE_SQL = "UPDATE source_snapshots SET archive_key = %s WHERE archive_key = %s"
# Storage moves made while a promotion holds its connection, applied once it lets go.
MOVES: ContextVar[list[tuple[str, str]] | None] = ContextVar("import_moved_keys", default=None)


@contextmanager
def recording_moves() -> Iterator[list[tuple[str, str]]]:
    pairs: list[tuple[str, str]] = []
    token = MOVES.set(pairs)
    try:
        yield pairs
    finally:
        MOVES.reset(token)


def note_moved(old_key: str, new_key: str) -> None:
    if (pairs := MOVES.get()) is not None:
        pairs.append((old_key, new_key))


async def moved(pairs: list[tuple[str, str]]) -> None:
    """Follow archived files to their new keys, or the change check could not load the old text."""
    if not pairs:
        return
    try:
        async with get_pool().connection() as conn:
            for old_key, new_key in pairs:
                await conn.execute(MOVE_SQL, (new_key, old_key))
    except Exception:
        logger.warning("snapshot keys not moved from %s", [old for old, _ in pairs], exc_info=True)


async def log_unfetched(slug: str, snapshot_ids: list[int], cited: list[str]) -> None:
    """Log a cited public URL no tool fetched in this run: a finding with no version behind it."""
    public = set()
    for u in cited:
        if not u or staff_sources.is_staff_source_url(u) or vault.is_vault_url(u):
            continue
        try:
            public.add(canonical_url(u))
        except Exception:  # noqa: BLE001 — the row is already saved; a bad URL must not fail the save
            logger.info("%s cites %s, which is not a URL that can be fetched", slug, u)
    if not public:
        return
    try:
        async with get_pool().connection() as conn:
            rows = await (await conn.execute(
                "SELECT url FROM source_snapshots WHERE id = ANY(%s)", (snapshot_ids,))).fetchall()
    except Exception:
        logger.warning("snapshots for %s not checked", slug, exc_info=True)
        return
    for url in sorted(public - {r["url"] for r in rows}):
        logger.info("%s cites %s, which no tool fetched in this run", slug, url)
