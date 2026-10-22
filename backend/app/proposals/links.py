"""A ticked file that is only a link: code fetches it once, under Import's checks, and keeps the copy for its reader."""

from __future__ import annotations

import logging
import re

from app.db.pool import get_pool
from app.ingest.access import canonical_url
from app.ingest.tools import research_tools
from app.integrations import storage

logger = logging.getLogger(__name__)

EXTRACTOR = "pitch_link_fetch/1"
_FAILED = ("REFUSED:", "ERROR:", "No readable text", "read_page failed", "fetch_document failed")
_HTTP = re.compile(r"returned HTTP (\d{3})")


def _reason(reply: str) -> str:
    """One short sentence of why, from a read_page or fetch_document reply."""
    if code := _HTTP.search(reply):
        return f"the site refused it: HTTP {code.group(1)}"
    if reply.startswith("REFUSED:"):
        return "Sangam may not read that site"
    if reply.startswith("No readable text"):
        return "the page had no text to read"
    if "larger than" in reply:
        return "it is too large to download"
    return "the site could not be reached"


async def archive(document_id: int, source_url: str) -> str | None:
    """Fetch the link and point its documents row at the saved copy. None when it worked, else why not."""
    if not source_url.startswith(("http://", "https://")):
        return "it has no web link to fetch"
    try:
        url = canonical_url(source_url)
        reply = await research_tools._read_page(url)
        if "Use fetch_document" in reply:  # a PDF or Word file, not a page
            reply = await research_tools._fetch_document(url, None)
        if reply.startswith(_FAILED):
            return _reason(reply)
        key = await storage.archived_key(storage.SOURCE_ARCHIVE, url)
        if key is None:
            return "it was read but could not be saved; try again"
        async with get_pool().connection() as conn:
            await conn.execute(
                "UPDATE documents SET storage_path = %s, content_hash = %s, fetched_at = now(), "
                "extractor_version = %s WHERE id = %s AND storage_path IS NULL",
                (storage.qualify(storage.SOURCE_ARCHIVE, key), storage.hash_from_key(key), EXTRACTOR, document_id),
            )
        return None
    except Exception as exc:  # noqa: BLE001 - one link's failure never stops the other readers
        logger.warning("fetching link %s failed (%s)", document_id, type(exc).__name__)
        return "it could not be fetched"
