"""A registry check a staff member made by hand, written through the identifier writer's precedence rule."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.ingest.records import IDENTIFIER_STATUSES, NEEDS_A_NUMBER, OrgIdentifierRecord
from app.ingest.writer import write_org_identifier

ID_TYPES: tuple[str, ...] = ("pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no")
NOTE_MAX = 500
_ORG_ID = re.compile(r"\[?org:(\d+)\]?|(\d+)")
_ROW = "SELECT id, org_id, id_value, status, source_type, evidence FROM org_identifiers WHERE "


def refusal(*, id_type: str, status: str, source_url: str, note: str, user_id: UUID | None) -> str | None:
    if user_id is None:
        return ("REFUSED: no signed-in staff member is attached to this conversation, so nobody can be "
                "recorded as having made the check. Nothing was written.")
    if id_type not in ID_TYPES:
        return f"REFUSED: id_type must be one of {', '.join(ID_TYPES)}, not {id_type!r}. Nothing was written."
    if status not in IDENTIFIER_STATUSES:
        return (f"REFUSED: status must be one of {', '.join(IDENTIFIER_STATUSES)}, not {status!r}. "
                "Nothing was written.")
    if not source_url.startswith(("http://", "https://")):
        return ("REFUSED: source_url must be the http(s) address of the registry that was checked. "
                "Nothing was written.")
    if len(note) > NOTE_MAX:
        return f"REFUSED: keep the note under {NOTE_MAX} characters. Nothing was written."
    return None


async def _orgs(conn: Any, org: str) -> list[dict]:
    key = org.strip()
    m = _ORG_ID.fullmatch(key)
    if m:
        sql, params = "SELECT id, name, slug FROM orgs WHERE id = %s", (int(m.group(1) or m.group(2)),)
    else:
        sql = "SELECT id, name, slug FROM orgs WHERE slug = %s OR lower(name) = lower(%s) ORDER BY id LIMIT 5"
        params = (key, key)
    return list(await (await conn.execute(sql, params)).fetchall())


async def _current(conn: Any, org_id: int, id_type: str) -> list[dict]:
    return list(await (await conn.execute(
        _ROW + "org_id = %s AND id_type = %s AND is_current ORDER BY id LIMIT 3", (org_id, id_type)
    )).fetchall())


async def _target(conn: Any, org_id: int, id_type: str, id_value: str | None) -> dict | None:
    """The row the writer landed on: by number, else the open row, else the one current row."""
    if id_value:
        return await (await conn.execute(
            _ROW + "org_id = %s AND id_type = %s AND lower(id_value) = lower(%s)", (org_id, id_type, id_value)
        )).fetchone()
    open_row = await (await conn.execute(
        _ROW + "org_id = %s AND id_type = %s AND id_value IS NULL", (org_id, id_type)
    )).fetchone()
    if open_row is not None:
        return open_row
    rows = await _current(conn, org_id, id_type)
    return rows[0] if len(rows) == 1 else None


async def record(
    pool: Any, *, org: str, id_type: str, status: str, source_url: str, id_value: str = "",
    application_ref: str = "", document_id: int | None = None, note: str = "", user_id: UUID | None,
) -> str:
    note = " ".join((note or "").split())
    id_type, status = (id_type or "").strip().lower(), (status or "").strip().lower()
    source_url, id_value = (source_url or "").strip(), (id_value or "").strip()
    why = refusal(id_type=id_type, status=status, source_url=source_url, note=note, user_id=user_id)
    if why:
        return why
    async with pool.connection() as conn, conn.transaction():
        staff = await (await conn.execute("SELECT is_staff FROM users WHERE id = %s", (user_id,))).fetchone()
        if not (staff and staff["is_staff"]):
            return "REFUSED: only a staff member's check is recorded, and this conversation is not staff's."
        orgs = await _orgs(conn, org)
        if not orgs:
            return f"REFUSED: no organisation in the catalog matches {org!r}. Pass its slug or its [org:N] id."
        if len(orgs) > 1:
            named = ", ".join(f"{o['name']} [org:{o['id']}] ({o['slug']})" for o in orgs)
            return f"REFUSED: {org!r} names more than one organisation: {named}. Pass the slug or [org:N]."
        target = orgs[0]
        cite = f"{target['name']} [org:{target['id']}]"

        doc = None
        if document_id is not None:
            doc = await (await conn.execute(
                "SELECT id, org_id, title FROM documents WHERE id = %s", (document_id,)
            )).fetchone()
            if doc is None or doc["org_id"] != target["id"]:
                owner = "does not exist" if doc is None else (
                    "belongs to no organisation" if doc["org_id"] is None else f"belongs to [org:{doc['org_id']}]")
                return (f"REFUSED: document {document_id} {owner}, so it cannot evidence a check of {cite}. "
                        "Upload the evidence to that organisation's Doc Vault, or record the check without "
                        "a document (it is then claimed). Nothing was written.")

        current = await _current(conn, target["id"], id_type)
        if len(current) > 1:
            listed = ", ".join(f"row {r['id']} ({r['id_value'] or 'no number'}, {r['status']})" for r in current)
            return (f"REFUSED: {cite} holds {len(current)} current {id_type} identifiers: {listed}. A person "
                    "decides which is current before a check is recorded. Nothing was written.")
        if not id_value and status in NEEDS_A_NUMBER and current and current[0]["id_value"]:
            id_value = current[0]["id_value"]       # a status about the one registration on file
        try:
            rec = OrgIdentifierRecord(
                entity_name=target["name"], id_type=id_type, id_value=id_value or None, status=status,
                application_ref=application_ref.strip() or None, check_method="manual_check",
                source_type="manual_check", evidence_tier="evidenced" if doc else "claimed",
                source_url=source_url, source_name="Manual registry check", fetched_at=datetime.now(UTC),
            )
        except ValidationError as exc:
            reason = "; ".join(e["msg"] for e in exc.errors())
            return f"REFUSED: {reason}. Pass id_value (or application_ref for 'applied'). Nothing was written."

        outcome, changes, conflicts = await write_org_identifier(conn, rec, target["id"], None)
        row = None if outcome == "held" else await _target(conn, target["id"], id_type, rec.id_value)
        took = row is not None and (outcome == "added" or "source_type" in changes)
        # Same source, same status: a document now evidences what an earlier check only claimed.
        upgrade = (outcome == "matched" and not conflicts and doc is not None and row is not None
                   and row["source_type"] == "manual_check" and row["evidence"] == "claimed"
                   and row["status"] == status)
        line = f"manual check {datetime.now(UTC):%Y-%m-%d}: {status}" + (f" — {note}" if note else "")
        if row is not None:
            if took or upgrade:
                await conn.execute(
                    "UPDATE org_identifiers SET checked_at = now(), checked_by = %s, "
                    "check_method = 'manual_check', evidence_document_id = %s, evidence = %s, "
                    "notes = concat_ws(E'\\n', notes, %s::text) WHERE id = %s",
                    (user_id, doc["id"] if doc else None, rec.evidence_tier, line, row["id"]),
                )
            else:
                # The attempt is kept on the row; its status, tier and checker stay as they were.
                await conn.execute(
                    "UPDATE org_identifiers SET notes = concat_ws(E'\\n', notes, %s::text) WHERE id = %s",
                    (line, row["id"]),
                )
        final = None if row is None else await (await conn.execute(
            _ROW + "id = %s", (row["id"],))).fetchone()

    number = rec.id_value or (final and final["id_value"]) or "no number on file"
    if outcome == "held":
        head = f"Not recorded for {cite}: {id_type} {number} is held by another organisation."
    elif took or upgrade:
        tier = (f"evidenced by document {doc['id']} ({doc['title'] or 'untitled'})" if doc else
                "claimed — no evidence document was given, so it does not count as evidenced until one is "
                "uploaded to the Doc Vault and the check recorded again with it")
        head = (f"Recorded a manual check for {cite}: {id_type} ({number}) is {status}, {tier}. "
                f"Identifier row {row['id']}.")
    else:
        kept = f"{final['status']} from {final['source_type'] or 'a person (unranked)'}" if final else "unchanged"
        head = (f"The manual check for {cite} did not change the stored {id_type} ({number}): it stays "
                f"{kept}. The attempt is noted on the row." if final else
                f"The manual check for {cite} found no single {id_type} row to note it on.")
    if status == "check_blocked":
        head += " check_blocked means the registry could not be read: it is never 'valid' and never 'not_found'."
    if conflicts:
        head += " Conflicts, kept for a person: " + " | ".join(c.describe() for c in conflicts)
    return head
