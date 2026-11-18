"""The versions of each page and report Scout read, kept so a later check can tell what changed."""

from __future__ import annotations

import logging

from app.db.pool import get_pool

logger = logging.getLogger(__name__)


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
