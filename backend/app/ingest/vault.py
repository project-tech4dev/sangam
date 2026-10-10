"""An organisation's Doc Vault as Import reads it: its private files, cited by page or cell.

Vault text only ever sits in the vault-reader, which has no web tools. Its findings live in
vault_research, one row per org, never in the shared entity_research row.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any

from app.agent.tools.files import extract_pdf_text
from app.ingest import staff_sources
from app.ingest.source_guards import PRIVATE_SOURCE_DOMAIN
from app.ingest.sources import url_host
from app.integrations import storage

URL_PREFIX = f"https://org-vault.{PRIVATE_SOURCE_DOMAIN}/"
MAX_BYTES = 50 * 1024 * 1024
# Bounded so a read never needs evicting to a file a web-reading agent could open.
MAX_CHARS = 24_000
PDF, XLSX = ".pdf", ".xlsx"

# What a funder's research may save from an org's own files: the funder's general facts. Facts about the
# org itself (its grants, amounts, contacts, results, the file) are shown on Review and held back.
PROMOTABLE = frozenset({"identity", "csr_year", "stated_geography", "eligibility_guideline", "rfp", "program"})

_MARKER = re.compile(r"\[vault:(\d+)#[^\]]+\]")
_PAGE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


def url(document_id: int) -> str:
    return f"{URL_PREFIX}{document_id}"


def is_vault_url(value: str | None) -> bool:
    return url_host(value or "") == f"org-vault.{PRIVATE_SOURCE_DOMAIN}"


def document_id(value: str | None) -> int | None:
    """The document a vault URL names, or None."""
    if not is_vault_url(value):
        return None
    tail = (value or "").rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def marked_ids(evidence: str | None) -> set[int]:
    return {int(m) for m in _MARKER.findall(evidence or "")}


async def documents(pool: Any, org_id: int) -> list[dict[str, Any]]:
    """The org's private uploads, newest first."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            "SELECT id, org_id, title, doc_type, storage_path, as_of, created_at FROM documents "
            "WHERE org_id = %s AND NOT is_public AND storage_path LIKE %s ORDER BY created_at DESC, id DESC",
            (org_id, f"{storage.ORG_VAULT}/%"),
        )).fetchall()


async def document(pool: Any, doc_id: int) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        return await (await conn.execute(
            "SELECT id, org_id, title, doc_type, storage_path, content_hash, as_of FROM documents "
            "WHERE id = %s AND NOT is_public AND storage_path LIKE %s",
            (doc_id, f"{storage.ORG_VAULT}/%"),
        )).fetchone()


async def in_vault(pool: Any, org_id: int, ids: set[int]) -> set[int]:
    """Which of `ids` are this org's own vault documents."""
    if not ids:
        return set()
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT id FROM documents WHERE id = ANY(%s) AND org_id = %s AND NOT is_public "
            "AND storage_path LIKE %s",
            (sorted(ids), org_id, f"{storage.ORG_VAULT}/%"),
        )).fetchall()
    return {r["id"] for r in rows}


def _head(doc: dict[str, Any]) -> list[str]:
    return [f"## document {doc['id']} · {doc.get('title') or 'untitled'} ({doc.get('doc_type') or 'file'})",
            f"A finding from it: source_url {url(doc['id'])} · source_type org_document"]


def pdf_text(doc: dict[str, Any], data: bytes, start_page: int, end_page: int | None) -> str:
    with tempfile.NamedTemporaryFile(suffix=PDF) as handle:
        handle.write(data)
        handle.flush()
        text, total = extract_pdf_text(Path(handle.name), start_page, end_page)
    if not text.strip():
        return "\n".join([*_head(doc), (f"{total} pages and no text in that range: most likely scanned. "
                                         "Say so; do not guess at its contents.")])
    text = _PAGE.sub(lambda m: f"[vault:{doc['id']}#p{m.group(1)}]", text)
    if len(text) > MAX_CHARS:
        text = text[:text.rfind("\n", 0, MAX_CHARS)] + (
            f"\n… cut at {MAX_CHARS} characters of {total} pages. Call again with a later start_page.")
    return "\n".join([*_head(doc), f"{total} pages. Cite a fact by the page marker before it.", "", text])


def xlsx_text(doc: dict[str, Any], data: bytes, sheet: str, start_row: int, limit: int) -> str:
    sheets, notes = staff_sources._browse(data, sheet, start_row, limit)
    body = staff_sources.render({"id": doc["id"], "source_name": doc.get("title") or "workbook",
                                 "source_url": url(doc["id"])}, sheets, marker="vault")
    text = "\n".join([*_head(doc), *notes, "Cite a fact by the marker of the cell that holds it.", body])
    if len(text) > MAX_CHARS:
        text = text[:text.rfind("\n", 0, MAX_CHARS)] + f"\n… cut at {MAX_CHARS} characters. Read one sheet."
    return text


async def read(doc: dict[str, Any], *, start_page: int = 1, end_page: int | None = None,
               sheet: str = "", start_row: int = 1, limit: int = 100) -> str:
    """One vault file's text, every line cited [vault:<id>#p<page>] or [vault:<id>#<sheet>!<cell>]."""
    parts = storage.split(doc["storage_path"] or "")
    if parts is None:
        return f"document {doc['id']} has no file on record."
    name = parts[1].lower()
    if not name.endswith((PDF, XLSX)):
        return f"document {doc['id']} is neither a PDF nor an .xlsx workbook, so it cannot be read here."
    data = await storage.download(*parts, max_bytes=MAX_BYTES)
    if data is None:
        return f"document {doc['id']} could not be downloaded."
    if name.endswith(PDF):
        return await asyncio.to_thread(pdf_text, doc, data, start_page, end_page)
    return await asyncio.to_thread(xlsx_text, doc, data, sheet, start_row, min(limit, staff_sources.BROWSE_MAX_ROWS))


def check_findings(findings: list[dict[str, Any]], vault_ids: set[int]) -> list[str]:
    """Why a vault save is refused: a finding not citing, by URL and marker, a document of this vault."""
    problems = []
    for f in findings:
        doc = document_id(f.get("source_url"))
        marks = marked_ids(f.get("evidence"))
        if doc is None:
            problems.append(f"{f.get('concept')}: source_url is not a vault document URL ({URL_PREFIX}<id>)")
        elif doc not in vault_ids:
            problems.append(f"{f.get('concept')}: document {doc} is not in this organisation's vault")
        elif doc not in marks:
            problems.append(f"{f.get('concept')}: the evidence lacks its [vault:{doc}#…] marker")
    return problems


def held_reason(f: dict[str, Any], entity_kind: str | None) -> str | None:
    """Why a vault finding is not saved to the catalog, naming no value; None when it is or is not a vault finding."""
    doc = document_id(f.get("source_url"))
    if doc is None:
        return None
    concept = f.get("concept")
    if doc not in marked_ids(f.get("evidence")):
        return f"{concept} from document {doc}: no [vault:{doc}#…] marker"
    if entity_kind == "org":
        return f"{concept} from document {doc}: an organisation's own documents stay with it"
    if concept not in PROMOTABLE:
        return f"{concept} from document {doc}: the organisation's own fact, kept private"
    return None


def hold_at_promote(findings: list[dict[str, Any]], entity_kind: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """(findings that may be saved, a held reason per vault finding that may not)."""
    reasons = [held_reason(f, entity_kind) for f in findings]
    return [f for f, r in zip(findings, reasons, strict=True) if r is None], [r for r in reasons if r]


async def document_rows(conn: Any, findings: list[dict[str, Any]]) -> dict[str, int]:
    """source_url -> the vault document row each kept finding cites, so a fact links to it."""
    ids = sorted({i for f in findings if (i := document_id(f.get("source_url"))) is not None})
    if not ids:
        return {}
    rows = await (await conn.execute(
        "SELECT id FROM documents WHERE id = ANY(%s) AND NOT is_public AND storage_path LIKE %s",
        (ids, f"{storage.ORG_VAULT}/%"),
    )).fetchall()
    return {url(r["id"]): r["id"] for r in rows}
