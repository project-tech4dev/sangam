"""Sangam's library: the public documents the catalog already holds, read from their archived copies.

Public by definition (documents.is_public), so a researcher may read them beside the web. A finding
cites the document's own source_url, as it would had the researcher fetched it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agent.tools.files import extract_pdf_text
from app.db.pool import get_pool
from app.ingest.matcher import resolve_funder, resolve_org
from app.ingest.promote import MERGEABLE
from app.ingest.vault import MAX_BYTES, MAX_CHARS
from app.integrations import storage

logger = logging.getLogger(__name__)

_PAGE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


async def _owners(conn: Any, name: str) -> tuple[int | None, int | None]:
    """(funder id, org id) the name resolves to without a person's say; either may be None."""
    funder = await resolve_funder(conn, name)
    org = await resolve_org(conn, name)
    return (funder.entity_id if funder.method in MERGEABLE else None,
            org.entity_id if org.method in MERGEABLE else None)


@tool
async def list_library_documents(name: str) -> str:
    """List the public documents Sangam already holds about one funder or NGO: annual reports, audit
    reports, CSR disclosures it archived earlier. Check here before searching the web for a report.

    Args:
        name: the organisation's name as asked.
    """
    try:
        async with get_pool().connection() as conn:
            funder_id, org_id = await _owners(conn, name)
            if funder_id is None and org_id is None:
                return f"Sangam's library has nothing filed under {name!r}."
            rows = await (await conn.execute(
                "SELECT id, title, doc_type, as_of, source_url, storage_path FROM documents "
                "WHERE is_public AND (funder_id = %s OR org_id = %s) ORDER BY as_of DESC NULLS LAST, id DESC",
                (funder_id, org_id),
            )).fetchall()
        if not rows:
            return f"Sangam's library holds no documents for {name!r}."
        lines = [f"{len(rows)} document(s) in Sangam's library for {name!r}:"]
        for r in rows:
            copy = ("archived copy: read_library_document"
                    if (r["storage_path"] or "").startswith(f"{storage.SOURCE_ARCHIVE}/") and
                    r["storage_path"].lower().endswith(".pdf") else "link only: read_page if websites are allowed")
            lines.append(f"  document {r['id']} · {r['title'] or 'untitled'} · {r['doc_type'] or 'document'} · "
                         f"{r['as_of'] or 'undated'} · {r['source_url']} · {copy}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("list_library_documents failed (%s)", type(exc).__name__)
        return f"list_library_documents failed: {type(exc).__name__}"


def _pdf(doc: dict[str, Any], data: bytes, start_page: int, end_page: int | None) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        text, total = extract_pdf_text(Path(handle.name), start_page, end_page)
    head = [f"## document {doc['id']} · {doc['title'] or 'untitled'}",
            f"A finding from it: source_url {doc['source_url']}. Quote the sentence; say which page."]
    if not text.strip():
        return "\n".join([*head, f"{total} pages and no text in that range: most likely scanned."])
    text = _PAGE.sub(lambda m: f"[page {m.group(1)}]", text)
    if len(text) > MAX_CHARS:
        text = text[:text.rfind("\n", 0, MAX_CHARS)] + (
            f"\n… cut at {MAX_CHARS} characters of {total} pages. Call again with a later start_page.")
    return "\n".join([*head, f"{total} pages.", "", text])


@tool
async def read_library_document(document_id: int, start_page: int = 1, end_page: int | None = None) -> str:
    """Read the archived copy of one document from Sangam's library, a page range at a time.

    Args:
        document_id: the id from list_library_documents.
        start_page: the first page to read, from 1.
        end_page: the last page to read; omit to read on until the output is cut.
    """
    try:
        async with get_pool().connection() as conn:
            doc = await (await conn.execute(
                "SELECT id, title, source_url, storage_path FROM documents WHERE id = %s AND is_public "
                "AND storage_path LIKE %s",
                (document_id, f"{storage.SOURCE_ARCHIVE}/%"),
            )).fetchone()
        if doc is None or not doc["storage_path"].lower().endswith(".pdf"):
            return f"Document {document_id} has no archived copy in Sangam's library."
        parts = storage.split(doc["storage_path"])
        data = await storage.download(*parts, max_bytes=MAX_BYTES) if parts else None
        if data is None:
            return f"Document {document_id} could not be downloaded."
        return await asyncio.to_thread(_pdf, dict(doc), data, start_page, end_page)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("read_library_document failed for %s (%s)", document_id, type(exc).__name__)
        return f"read_library_document failed: {type(exc).__name__}"
