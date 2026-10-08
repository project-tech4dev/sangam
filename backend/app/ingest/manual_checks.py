"""A registry check a staff member made by hand: equal-rank rows here, everything else through the writer."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.ingest.records import IDENTIFIER_STATUSES, NEEDS_A_NUMBER, OrgIdentifierRecord
from app.ingest.writer import Conflict, write_org_identifier

ID_TYPES: tuple[str, ...] = ("pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no")
NOTE_MAX = 500
IST = timezone(timedelta(hours=5, minutes=30), "IST")
_ORG_ID = re.compile(r"\[?org:(\d+)\]?|(\d+)")
_ROW = ("SELECT id, org_id, id_value, status, source_type, evidence, checked_at, valid_from, valid_until, "
        "application_ref, source_url, evidence_document_id FROM org_identifiers WHERE ")
# Equal in rank to a manual check; between equals a newer dated check wins, since registrations lapse.
_EQUAL = frozenset({"registry", "manual_check"})
# An undated open row a numbered check may take; a stated registration or lapse without a date is a conflict.
_OPEN_REPLACEABLE = frozenset({"applied", "provisional", "not_found", "check_blocked"})


def day(ts: datetime) -> str:
    return f"{ts.astimezone(IST):%Y-%m-%d}"


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


def check_instant(checked_on: str, now: datetime) -> datetime | str:
    """When the check was made: today (IST) is now; an earlier date is its IST noon. A string is a refusal."""
    if not (checked_on or "").strip():
        return now
    try:
        day = date.fromisoformat(checked_on.strip())
    except ValueError:
        return f"REFUSED: checked_on must be a date like 2026-10-08, not {checked_on!r}. Nothing was written."
    today = now.astimezone(IST).date()
    if day > today:
        return "REFUSED: checked_on is in the future. Nothing was written."
    return now if day == today else datetime.combine(day, time(12), IST)


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


async def _target(conn: Any, org_id: int, id_type: str, id_value: str | None, *, lock: bool = False) -> dict | None:
    """The row the writer would land on: by number (None if another org holds it), else the open row,
    else for a numberless check the one current row."""
    tail = " FOR UPDATE" if lock else ""
    if id_value:
        row = await (await conn.execute(
            _ROW + "id_type = %s AND lower(id_value) = lower(%s)" + tail, (id_type, id_value),
        )).fetchone()
        if row is not None:
            return row if row["org_id"] == org_id else None
    open_row = await (await conn.execute(
        _ROW + "org_id = %s AND id_type = %s AND id_value IS NULL" + tail, (org_id, id_type)
    )).fetchone()
    if open_row is not None or id_value:
        return open_row
    rows = list(await (await conn.execute(
        _ROW + "org_id = %s AND id_type = %s AND is_current ORDER BY id LIMIT 2" + tail, (org_id, id_type)
    )).fetchall())
    return rows[0] if len(rows) == 1 else None


def _replaced(row: dict) -> str:
    parts = [f"replaced {row['status']}", row["source_type"] or "unranked", row["evidence"] or "no tier"]
    if row["valid_from"]:
        parts.append(f"valid from {row['valid_from']:%Y-%m-%d}")
    if row["valid_until"]:
        parts.append(f"valid to {row['valid_until']:%Y-%m-%d}")
    parts.append(f"source {row['source_url'] or 'none recorded'}")
    if row["evidence_document_id"]:
        parts.append(f"document {row['evidence_document_id']}")
    parts.append(f"checked {day(row['checked_at'])}" if row["checked_at"] else "never dated")
    return ", ".join(parts)


async def _stamp(conn: Any, row_id: int, rec: OrgIdentifierRecord, *, checked_at: datetime, user_id: UUID,
                 doc: dict | None, line: str, replace: bool = False) -> None:
    """Who checked and when; a number or reference fills a blank. Without replace a document upgrades to
    evidenced and its absence never downgrades; with it the check takes status, tier, evidence and provenance."""
    sets = ["checked_at = %s", "checked_by = %s", "check_method = 'manual_check'",
            "notes = concat_ws(E'\\n', notes, %s::text)", "id_value = coalesce(id_value, %s)"]
    params: list[Any] = [checked_at, user_id, line, rec.id_value]
    if replace:
        sets += ["status = %s", "source_type = 'manual_check'", "evidence = %s", "evidence_document_id = %s",
                 "application_ref = coalesce(%s, application_ref)", "valid_from = NULL", "valid_until = NULL",
                 "as_of = NULL", "document_id = NULL", "archive_url = NULL", "source_url = %s", "source_name = %s", "fetched_at = %s"]
        params += [rec.status, rec.evidence_tier, doc["id"] if doc else None, rec.application_ref,
                   rec.source_url, rec.source_name, rec.fetched_at]
    else:
        sets.append("application_ref = coalesce(application_ref, %s)")
        params.append(rec.application_ref)
        if doc is not None:
            sets += ["evidence_document_id = %s", "evidence = 'evidenced'"]
            params.append(doc["id"])
    await conn.execute(f"UPDATE org_identifiers SET {', '.join(sets)} WHERE id = %s", (*params, row_id))


async def record(
    pool: Any, *, org: str, id_type: str, status: str, source_url: str, id_value: str = "",
    application_ref: str = "", document_id: int | None = None, note: str = "", checked_on: str = "",
    user_id: UUID | None,
) -> str:
    note = " ".join((note or "").split())
    id_type, status = (id_type or "").strip().lower(), (status or "").strip().lower()
    source_url, id_value = (source_url or "").strip(), (id_value or "").strip()
    why = refusal(id_type=id_type, status=status, source_url=source_url, note=note, user_id=user_id)
    if why:
        return why
    checked_at = check_instant(checked_on, datetime.now(UTC))
    if isinstance(checked_at, str):
        return checked_at
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
                "SELECT id, org_id, title FROM documents WHERE id = %s FOR SHARE", (document_id,)
            )).fetchone()
            if doc is None or doc["org_id"] != target["id"]:
                owner = "does not exist" if doc is None else (
                    "belongs to no organisation" if doc["org_id"] is None else f"belongs to [org:{doc['org_id']}]")
                return (f"REFUSED: document {document_id} {owner}, so it cannot evidence a check of {cite}. "
                        "Upload the evidence to that organisation's Doc Vault, or record the check without "
                        "a document (it is then claimed). Nothing was written.")

        if not id_value:
            # Only a numberless check borrows the number on file, so only it needs that number to be one.
            current = await _current(conn, target["id"], id_type)
            if len(current) > 1:
                listed = ", ".join(f"row {r['id']} ({r['id_value'] or 'no number'}, {r['status']})" for r in current)
                return (f"REFUSED: {cite} holds {len(current)} current {id_type} identifiers: {listed}. Pass the "
                        "number the check was about, or a person decides which is current. Nothing was written.")
            if status in NEEDS_A_NUMBER and current and current[0]["id_value"]:
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

        line = f"{day(checked_at)} manual_check: {status}" + (f" — {note}" if note else "")
        conflicts: list[Conflict] = []
        replaced = ""
        stored = await _target(conn, target["id"], id_type, rec.id_value, lock=True)
        # An equal-rank, unblocked row is decided here, so the writer never fills it. A numbered check leaves a
        # person's row, and an open row dated after it, to the writer, which then keeps the number on its own row.
        when = stored and stored["checked_at"]
        newer = when is None or checked_at > when
        mine = (stored is not None and status != "applied" and stored["status"] != "check_blocked"
                and (stored["source_type"] in _EQUAL or (stored["source_type"] is None and not rec.id_value))
                and not (rec.id_value and stored["id_value"] is None and not newer))
        if mine:
            equal = stored["source_type"] in _EQUAL
            # A numbered check may take an undated open row only when that row names no live registration.
            fills_open = (rec.id_value is not None and stored["id_value"] is None and when is None
                          and stored["status"] in _OPEN_REPLACEABLE)
            if stored["status"] == status and equal and (newer or (doc is not None and checked_at >= when)):
                outcome = "confirmed"
                if rec.application_ref and stored["application_ref"] not in (None, rec.application_ref):
                    conflicts.append(Conflict(
                        "org_identifiers", f"[org:{target['id']}] {id_type}", "application_ref",
                        stored["application_ref"], stored["source_type"], stored["source_url"],
                        rec.application_ref, "manual_check", source_url))
                earlier = stored["evidence_document_id"]
                if doc is not None and earlier not in (None, doc["id"]):
                    line += f" (evidence document {doc['id']} replaces document {earlier})"
                await _stamp(conn, stored["id"], rec, checked_at=checked_at, user_id=user_id, doc=doc, line=line)
            elif (status != "check_blocked" and stored["status"] != status and equal
                  and ((when is not None and newer) or fills_open)):
                outcome, replaced = "replaced", _replaced(stored)
                await _stamp(conn, stored["id"], rec, checked_at=checked_at, user_id=user_id, doc=doc,
                             line=f"{line} ({replaced})", replace=True)
            else:
                outcome = "noted"
                if stored["status"] != status:
                    conflicts.append(Conflict(
                        "org_identifiers", f"[org:{target['id']}] {id_type}", "status", stored["status"],
                        stored["source_type"], stored["source_url"], status, "manual_check", source_url))
                await conn.execute(
                    "UPDATE org_identifiers SET notes = concat_ws(E'\\n', notes, %s::text), "
                    "application_ref = coalesce(application_ref, %s) WHERE id = %s",
                    (line, rec.application_ref if stored["status"] == status else None, stored["id"]),
                )
            row = stored
        else:
            outcome, changes, conflicts = await write_org_identifier(conn, rec, target["id"], None)
            row = None if outcome == "held" else await _target(conn, target["id"], id_type, rec.id_value)
            if (row is not None and stored is not None and row["id"] == stored["id"]
                    and ("source_type" in changes or "status" in changes)):
                replaced = _replaced(stored)
                line = f"{line} ({replaced})"
            if row is not None and (outcome == "added" or "source_type" in changes or "status" in changes):
                outcome = "taken"
                await _stamp(conn, row["id"], rec, checked_at=checked_at, user_id=user_id, doc=doc, line=line)
                if doc is None:
                    await conn.execute("UPDATE org_identifiers SET evidence_document_id = NULL WHERE id = %s",
                                       (row["id"],))
            elif row is not None:
                await conn.execute(
                    "UPDATE org_identifiers SET notes = concat_ws(E'\\n', notes, %s::text) WHERE id = %s",
                    (line, row["id"]),
                )
        final = None if row is None else await (await conn.execute(
            _ROW + "id = %s", (row["id"],))).fetchone()

    number = rec.id_value or (final and final["id_value"]) or "no number on file"
    tier = (f"evidenced by document {doc['id']} ({doc['title'] or 'untitled'})" if doc else
            "claimed — no evidence document was given, so it does not count as evidenced until one is "
            "uploaded to the Doc Vault and the check recorded again with it")
    if outcome == "held":
        head = f"Not recorded for {cite}: {id_type} {number} is held by another organisation."
    elif outcome in ("taken", "replaced"):
        head = (f"Recorded a manual check for {cite}: {id_type} ({number}) is {status}, {tier}. "
                f"Identifier row {final['id']}.")
        if replaced:
            head += (f" A newer check of equal rank supersedes the earlier one: {replaced}." if outcome == "replaced"
                     else f" It supersedes the stored value: {replaced}.")
    elif outcome == "confirmed":
        kept = "evidenced" if final["evidence"] == "evidenced" else tier
        head = (f"Confirmed {cite}: {id_type} ({number}) is still {status} ({final['source_type']}, {kept}); "
                f"checked {day(checked_at)} by a staff member. Identifier row {final['id']}.")
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
