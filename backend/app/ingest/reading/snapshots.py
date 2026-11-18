"""The versions of each page and report Scout read, kept so a later check can tell what changed."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.db.pool import get_pool
from app.ingest.reading import staff_sources, vault

logger = logging.getLogger(__name__)

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


async def record_snapshot(url: str, kind: str, fingerprint: str, archive_key: str | None) -> int | None:
    """The id of this version of url, from text_hash or document_hash; an unchanged re-read bumps last_seen_at.
    Never raises: a read must not fail because its bookkeeping did."""
    try:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(
                    """
                    INSERT INTO source_snapshots (url, kind, text_hash, archive_key)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (url, text_hash) DO UPDATE SET
                        last_seen_at = now(),
                        archive_key = COALESCE(source_snapshots.archive_key, EXCLUDED.archive_key)
                    RETURNING id
                    """,
                    (url, kind, fingerprint, archive_key),
                )
            ).fetchone()
        return row["id"] if row else None
    except Exception:  # noqa: BLE001 - logged, never raised
        logger.warning("record_snapshot failed for %s", url, exc_info=True)
        return None
