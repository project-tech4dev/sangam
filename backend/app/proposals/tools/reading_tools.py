"""Reading for a proposal: the supervisor's read_files, and the tools its two readers use. No tool here reads the web."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import tool

from app.db.pool import get_pool
from app.ingest import vault
from app.ingest.brief import headline, record
from app.ingest.source_guards import is_private_source
from app.ingest.tools.library_tools import _pdf
from app.ingest.vault import MAX_BYTES
from app.integrations import storage
from app.proposals import context, steps
from app.proposals.tools.proposal_tools import NO_PROPOSAL, require_edit

logger = logging.getLogger(__name__)

BRIEF_FACTS = 80  # a long brief is cut; the reader is told so


async def _slug(conn: Any, side: str, entity_id: int) -> str | None:
    """The brief's slug: the research row resolved to this entity first, then the catalog's own slug."""
    column, table = ("resolved_funder_id", "funders") if side == "funder" else ("resolved_org_id", "orgs")
    row = await (await conn.execute(
        f"SELECT slug FROM entity_research WHERE {column} = %s ORDER BY researched_at DESC LIMIT 1", (entity_id,)
    )).fetchone()
    if row is None:
        row = await (await conn.execute(f"SELECT slug FROM {table} WHERE id = %s", (entity_id,))).fetchone()
    return row["slug"] if row else None


def _fact_line(f: dict[str, Any]) -> str:
    when = f.get("fiscal_year") or f.get("as_of") or ""
    return (f"- {f.get('concept')}: {headline(f)}" + (f" · {when}" if when else "")
            + f" · {f.get('source_name') or 'source'} {f.get('source_url')}"
            + f"\n  quote: \"{' '.join(str(f.get('evidence') or '').split())}\"")


@tool
async def read_brief(side: str = "funder") -> str:
    """Read what Sangam's research brief says about this proposal's funder or organisation: each fact with its
    public link and the sentence it quotes. Add one as a web fact with that link and quote.

    Args:
        side: "funder" or "org".
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if side not in ("funder", "org"):
            return 'side is "funder" or "org".'
        name, entity_id = (p.funder_name, p.funder_id) if side == "funder" else (p.org_name, p.org_id)
        async with get_pool().connection() as conn:
            slug = await _slug(conn, side, entity_id)
        data = await storage.read(storage.SOURCE_ARCHIVE, storage.brief_key(slug)) if slug else None
        if data is None:
            return f"Sangam holds no research brief for {name}. Say so; do not guess what it would hold."
        facts, _ = record(data.decode("utf-8"))
        # A private file's words never leave the proposal they were read for.
        public = [f for f in facts if str(f.get("source_url") or "").startswith("http")
                  and not is_private_source(f.get("source_url"))]
        if not public:
            return f"Sangam's brief for {name} holds no public facts."
        lines = [f"Sangam's research brief for {name}: {len(public)} fact(s)."]
        lines += [_fact_line(f) for f in public[:BRIEF_FACTS]]
        if len(public) > BRIEF_FACTS:
            lines.append(f"… {len(public) - BRIEF_FACTS} more not shown.")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("read_brief failed (%s)", type(exc).__name__)
        return f"read_brief failed: {type(exc).__name__}"


async def _public_pdf(document_id: int, where: str, args: tuple[Any, ...], start_page: int,
                      end_page: int | None) -> str | None:
    async with get_pool().connection() as conn:
        doc = await (await conn.execute(
            f"SELECT id, title, source_url, storage_path FROM documents WHERE id = %s AND is_public "
            f"AND storage_path LIKE %s {where}",
            (document_id, f"{storage.SOURCE_ARCHIVE}/%", *args),
        )).fetchone()
    if doc is None or not doc["storage_path"].lower().endswith(".pdf"):
        return None
    parts = storage.split(doc["storage_path"])
    data = await storage.download(*parts, max_bytes=MAX_BYTES) if parts else None
    if data is None:
        return f"Document {document_id} could not be downloaded."
    return await asyncio.to_thread(_pdf, dict(doc), data, start_page, end_page)


@tool
async def list_funder_documents() -> str:
    """List the public documents Sangam archived for this proposal's funder: annual reports, CSR policies, calls."""
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        async with get_pool().connection() as conn:
            rows = await (await conn.execute(
                "SELECT id, title, doc_type, as_of FROM documents WHERE funder_id = %s AND is_public "
                "AND storage_path LIKE %s AND lower(storage_path) LIKE '%%.pdf' ORDER BY as_of DESC NULLS LAST, id DESC",
                (p.funder_id, f"{storage.SOURCE_ARCHIVE}/%"),
            )).fetchall()
        if not rows:
            return f"Sangam has archived no documents for {p.funder_name}."
        return "\n".join([f"{len(rows)} document(s) Sangam archived for {p.funder_name}:",
                          *[f"  document {r['id']} · {r['title'] or 'untitled'} · {r['doc_type'] or 'document'} · "
                            f"{r['as_of'] or 'undated'}" for r in rows]])
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("list_funder_documents failed (%s)", type(exc).__name__)
        return f"list_funder_documents failed: {type(exc).__name__}"


@tool
async def read_funder_document(document_id: int, start_page: int = 1, end_page: int | None = None) -> str:
    """Read one of this funder's archived documents, a page range at a time. A fact from it is a web fact citing
    the document's link and quoting the sentence.

    Args:
        document_id: the id from list_funder_documents.
        start_page: the first page, from 1.
        end_page: the last page; omit to read on until the output is cut.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        text = await _public_pdf(document_id, "AND funder_id = %s", (p.funder_id,), start_page, end_page)
        return text or f"Document {document_id} is not one of {p.funder_name}'s archived documents."
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("read_funder_document failed for %s (%s)", document_id, type(exc).__name__)
        return f"read_funder_document failed: {type(exc).__name__}"


@tool
async def read_template(start_page: int = 1, end_page: int | None = None) -> str:
    """Read the funder's own proposal form chosen in step 2: its sections and questions, a page range at a time.

    Args:
        start_page: the first page (or paragraph, in a Word file), from 1.
        end_page: the last page; omit to read on until the output is cut.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        doc_id = (p.work.get("template") or {}).get("document_id")
        if not doc_id:
            return "No funder form was chosen for this proposal: it follows Sangam's usual order."
        pool = get_pool()
        doc = await vault.document(pool, doc_id)
        if doc is not None and doc["org_id"] == p.org_id:
            return await vault.read(doc, start_page=start_page, end_page=end_page)
        text = await _public_pdf(doc_id, "", (), start_page, end_page)
        return text or "The funder's form has no copy Sangam can read."
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure
        logger.warning("read_template failed (%s)", type(exc).__name__)
        return f"read_template failed: {type(exc).__name__}"


@tool
async def read_files() -> str:
    """Read the files ticked in step 2, and what Sangam holds on the funder, into the fact list. Call it when the
    person presses "Write the first draft" or asks to read the files again.

    One reader per file runs at once. Only files not read yet, or that failed, are read: calling it again after a
    failure retries just those. It takes a few minutes and returns what each reader found or why it failed.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if refused := require_edit(p):
            return refused
        if early := steps.too_early("read_files", int(p.work.get("stage") or 1)):
            return f"REFUSED: {early}."
        from app.proposals import readers  # built with the agent, from this module's tools

        return await readers.read(p)
    except Exception as exc:
        logger.exception("read_files failed")
        return f"read_files failed: {type(exc).__name__}"
