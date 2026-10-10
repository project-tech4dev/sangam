"""An organisation's Doc Vault: list its files, read one, save what it says. The vault-reader's alone.

Each tool checks the run's caller can read that organisation: the tools use the owner pool, so RLS
does not. A file the caller may not read and a file that does not exist get the same answer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from app.db.pool import get_pool
from app.ingest import vault
from app.ingest.caller import scope
from app.ingest.research_records import VaultResearch
from app.ingest.writer import slugify

logger = logging.getLogger(__name__)


async def _org(pool: Any, org: str) -> dict[str, Any] | str:
    """The organisation the caller named, or the one they belong to; a refusal string otherwise."""
    caller = scope()
    org = org.strip().removeprefix("[org:").removesuffix("]")
    if not org:
        readable = list(caller.org_roles)
        if len(readable) != 1:
            return "Name the organisation whose documents to list (its id, slug or name)."
        org = str(readable[0])
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT id, name, slug FROM orgs WHERE id::text = %s OR slug = %s OR lower(name) = lower(%s) "
            "ORDER BY (id::text = %s) DESC, id LIMIT 1",
            (org, org, org, org),
        )).fetchone()
    if row is None or not caller.can_read_org(row["id"]):
        return f"No Doc Vault you can read for {org!r}."
    return dict(row)


@tool
async def list_vault_documents(org: str = "") -> str:
    """List the private files in one organisation's Doc Vault: id, title, type and date.

    Args:
        org: the organisation's id, slug or name. Leave empty for the person's own organisation.
    """
    try:
        pool = get_pool()
        found = await _org(pool, org)
        if isinstance(found, str):
            return found
        docs = await vault.documents(pool, found["id"])
        if not docs:
            return f"{found['name']} (org_id {found['id']}) has no files in its Doc Vault."
        lines = [f"{found['name']} (org_id {found['id']}): {len(docs)} file(s) in its Doc Vault."]
        for d in docs:
            when = d["as_of"] or (d["created_at"].date().isoformat() if d.get("created_at") else "undated")
            lines.append(f"  document {d['id']} · {d['title'] or 'untitled'} · {d['doc_type'] or 'file'} · {when}")
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("list_vault_documents failed")
        return f"list_vault_documents failed: {type(exc).__name__}"


@tool
async def read_vault_document(
    document_id: int, start_page: int = 1, end_page: int | None = None, sheet: str = "", start_row: int = 1
) -> str:
    """Read one Doc Vault file. Every line carries its citation marker.

    A PDF reads a page range at a time, each page headed [vault:<id>#p<page>]; omit end_page to read
    on until the output is cut, then continue from a later start_page. An .xlsx workbook without
    `sheet` lists its sheets; with `sheet` it reads rows from start_row, each cited
    [vault:<id>#<sheet>!<cell>].

    Args:
        document_id: the id from list_vault_documents.
        start_page: a PDF's first page to read, from 1.
        end_page: a PDF's last page to read.
        sheet: a workbook's sheet name.
        start_row: a workbook's first row to read.
    """
    try:
        doc = await vault.document(get_pool(), document_id)
        if doc is None or not scope().can_read_org(doc["org_id"]):
            return f"No Doc Vault file {document_id} you can read."
        return await vault.read(doc, start_page=start_page, end_page=end_page, sheet=sheet, start_row=start_row)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure; the type only, as a message could quote the file
        logger.warning("read_vault_document failed for %s (%s)", document_id, type(exc).__name__)
        return f"read_vault_document failed: {type(exc).__name__}"


@tool
async def save_vault_findings(findings: VaultResearch) -> str:
    """Save what one organisation's own files say about one entity. Call this LAST, once.

    Every finding needs source_url https://org-vault.sangam.invalid/<document id>, source_type
    org_document where it has that field, and evidence quoting the line with its [vault:…] marker. A finding citing a file
    outside this organisation's vault, or without its marker, refuses the whole save: fix it and
    call again.

    Args:
        findings: the entity as asked, the organisation whose vault you read, and what it says.
    """
    caller = scope()
    if not caller.can_read_org(findings.org_id):
        return "REFUSED: you cannot read that organisation's Doc Vault."
    if findings.entity_kind == "org" and not caller.can_research_org(findings.org_id):
        return "REFUSED: researching an NGO is for its stewards and the Sangam team."
    try:
        pool = get_pool()
        payload = [f.model_dump(mode="json") for f in findings.findings]
        cited = {vault.document_id(f["source_url"]) for f in payload} | set(findings.documents_read)
        own = await vault.in_vault(pool, findings.org_id, {i for i in cited if i is not None})
        problems = vault.check_findings(payload, own)
        problems += [f"document {d} is not in this organisation's vault"
                     for d in findings.documents_read if d not in own]
        if problems:
            return "REFUSED, nothing saved:\n" + "\n".join(f"  {p}" for p in problems)
        slug = slugify(findings.entity_name)
        async with pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                """
                INSERT INTO vault_research (slug, org_id, entity_name, entity_kind, findings, gaps,
                                            documents_read, fact_count, researched_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                ON CONFLICT (slug, researched_on, org_id) DO UPDATE SET
                    entity_name = EXCLUDED.entity_name, entity_kind = EXCLUDED.entity_kind,
                    findings = EXCLUDED.findings, gaps = EXCLUDED.gaps,
                    documents_read = EXCLUDED.documents_read, fact_count = EXCLUDED.fact_count,
                    researched_by = EXCLUDED.researched_by, researched_at = now()
                RETURNING id
                """,
                (slug, findings.org_id, findings.entity_name, findings.entity_kind, json.dumps(payload),
                 json.dumps([g.model_dump(mode="json") for g in findings.gaps]),
                 sorted(set(findings.documents_read)), len(payload), caller.user_id),
            )).fetchone()
        found = ", ".join(findings.concepts_found()) or "nothing"
        return (f"Saved as vault_research #{row['id']} ({slug}): {len(payload)} findings across {found}. "
                f"Report back with slug={slug!r} and saved=true.")
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure, naming only its type
        logger.warning("save_vault_findings failed for %s (%s)", findings.entity_name, type(exc).__name__)
        return f"save_vault_findings failed: {type(exc).__name__}. Report the failure without quoting the files."
