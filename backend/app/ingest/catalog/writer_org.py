"""Writes an org: its row, identifiers, financials and places, each ranked on the evidence tier."""

from __future__ import annotations

from typing import Any

from app.ingest.catalog.matcher import TRIGRAM_FLOOR, Match, name_key
from app.ingest.catalog.rows import (
    OrgFinancialsRecord,
    OrgIdentifierRecord,
    OrgLocationRecord,
    OrgRecord,
)
from app.ingest.catalog.writer import (
    GATE,
    Conflict,
    Owner,
    Tier,
    diff_row,
    free_slug,
    may_overwrite,
    new_aliases,
    outranks,
    plain,
    ranked_changes,
    slugify,
    takes_row,
    upsert_ranked,
)

ORG_UPDATABLE = ("org_kind", "legal_form", "registration_date", "website", "description",
                 "staff_count", "staff_count_note", "registered_address", "parent_id")


ORG_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of",
                  "content_hash", "extractor_version")


ORG_FINANCIALS_KEY = ("org_id", "fiscal_year")


ORG_FINANCIALS_VALUES = ("total_income", "program_spend", "non_program_spend", "foreign_contribution",
                         "foreign_unspent", "is_audited", "notes")


ORG_LOCATION_KEY = ("org_id", "location_id")


ORG_LOCATION_VALUES = ("role", "note", "program_id")


async def write_org(
    conn: Any, rec: OrgRecord, match: Match, *, parent_id: int | None = None
) -> tuple[str, int, dict, list[Conflict]]:
    """Returns (status, org_id, changes, conflicts). Status is added | updated | matched.
    Aliases are appended, never replaced, whatever the tier: a spelling a source used still finds the org."""
    proposed = {c: getattr(rec, c, None) for c in ORG_UPDATABLE} | {"parent_id": parent_id}
    provenance = {c: getattr(rec, c) for c in ORG_PROVENANCE}
    tier = Tier.of(rec)
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT name, aliases, source_type, evidence, source_url, {', '.join(ORG_UPDATABLE)} "
                "FROM orgs WHERE id = %s FOR UPDATE",
                (match.entity_id,),
            )
        ).fetchone()
        write, kept = ranked_changes(dict(existing), proposed, existing["source_type"], tier.source_type)
        conflicts = [
            Conflict("orgs", f"[org:{match.entity_id}]", c, old, existing["source_type"],
                     existing["source_url"], new, tier.source_type, rec.source_url)
            for c, old, new in kept
        ]
        retier = takes_row(existing, proposed, tier)
        held = list(existing["aliases"] or [])
        added = new_aliases(held, rec.aliases, existing["name"])
        if not write and not added and not retier:
            return "matched", match.entity_id, {}, conflicts
        sets = {c: proposed[c] for c in write}
        if retier:
            sets.update({c: v for c, v in provenance.items() if v is not None})
            sets.update(source_type=tier.source_type, evidence=tier.evidence)
        clauses = [f"{c} = %s" for c in sets]
        values = list(sets.values())
        changes = {**write, **retier}
        if added:
            clauses.append("aliases = aliases || %s::text[]")
            values.append(added)
            changes["aliases"] = {"old": held, "new": [*held, *added]}
        await conn.execute(
            f"UPDATE orgs SET {', '.join(clauses)} WHERE id = %s", (*values, match.entity_id)
        )
        return "updated", match.entity_id, changes, conflicts

    slug = await free_slug(conn, slugify(rec.name), "orgs")
    row = await (
        await conn.execute(
            "INSERT INTO orgs (slug, name, org_kind, legal_form, registration_date, website, description, "
            "aliases, staff_count, staff_count_note, registered_address, parent_id, registry_status, "
            "source_type, evidence, source_url, source_name, fetched_at, as_of, content_hash, extractor_version) "
            "VALUES (%s, %s, COALESCE(%s, 'cso'), %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', %s, %s, "
            "%s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.org_kind, rec.legal_form, rec.registration_date, rec.website,
             rec.description, new_aliases([], rec.aliases, rec.name), rec.staff_count,
             rec.staff_count_note, rec.registered_address, parent_id, tier.source_type, tier.evidence, *provenance.values()),
        )
    ).fetchone()
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}, []


async def org_alias_holders(conn: Any, spellings: list[str], org_id: int | None) -> dict[str, dict]:
    """name_key(spelling) -> {"id", "name"} of ANOTHER organisation that answers to it, by name or alias.
    Keyed as resolve_org compares, so a spelling it would resolve to that org is caught here too."""
    keys = {name_key(s) for s in spellings if s and name_key(s)}
    if not keys:
        return {}
    texts = sorted({s for s in spellings if s})
    rows = await (
        await conn.execute(
            "SELECT id, name, aliases FROM orgs WHERE id IS DISTINCT FROM %s AND EXISTS ("
            "SELECT 1 FROM unnest(%s::text[]) AS s WHERE lower(name) = lower(s) OR similarity(name, s) >= %s "
            "OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(s) "
            "OR similarity(a, s) >= %s)) ORDER BY id",
            (org_id, texts, TRIGRAM_FLOOR, TRIGRAM_FLOOR),
        )
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        for key in sorted({name_key(n) for n in (r["name"], *(r["aliases"] or []))} & keys):
            out.setdefault(key, {"id": r["id"], "name": r["name"]})
    return out


ORG_IDENTIFIER_VALUES = ("id_value", "status", "valid_from", "valid_until", "application_ref",
                         "check_method", "notes")


# org_identifiers has no content_hash or extractor_version.
ORG_IDENTIFIER_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of")


async def write_org_identifier(
    conn: Any, rec: OrgIdentifierRecord, org_id: int, document_id: int | None
) -> tuple[str, dict, list[Conflict]]:
    """One registration with its status: (added | updated | matched | held, changes, conflicts).
    Two sources' disagreeing facts are two rows; a strictly stronger source superseding a weaker one is one."""
    cols = ", ".join(ORG_IDENTIFIER_VALUES)
    head = f"SELECT id, org_id, {cols}, source_type, evidence, source_url FROM org_identifiers WHERE "
    proposed = {c: getattr(rec, c) for c in ORG_IDENTIFIER_VALUES}
    provenance = {c: getattr(rec, c) for c in ORG_IDENTIFIER_PROVENANCE}
    tier = Tier.of(rec)

    def conflict(stored: dict, col: str, old: Any, new: Any) -> Conflict:
        return Conflict("org_identifiers", f"[org:{org_id}] {rec.id_type}", col, old, stored["source_type"],
                        stored["source_url"], new, tier.source_type, rec.source_url)

    async def insert(conflicts: list[Conflict]) -> tuple[str, dict, list[Conflict]]:
        fresh = {"org_id": org_id, "id_type": rec.id_type,
                 **{c: v for c, v in proposed.items() if v is not None},
                 **{c: v for c, v in provenance.items() if v is not None},
                 "source_type": tier.source_type, "evidence": tier.evidence, "document_id": document_id}
        await conn.execute(
            f"INSERT INTO org_identifiers ({', '.join(fresh)}) VALUES ({', '.join(['%s'] * len(fresh))})",
            tuple(fresh.values()),
        )
        return "added", {c: {"old": None, "new": plain(v)} for c, v in fresh.items()}, conflicts

    async def open_row() -> dict | None:
        return await (
            await conn.execute(head + "org_id = %s AND id_type = %s AND id_value IS NULL FOR UPDATE",
                               (org_id, rec.id_type))
        ).fetchone()

    pending: list[Conflict] = []
    if rec.id_value:
        target = await (
            await conn.execute(head + "id_type = %s AND lower(id_value) = lower(%s) FOR UPDATE",
                               (rec.id_type, rec.id_value))
        ).fetchone()
        if target is not None and target["org_id"] != org_id:
            return "held", {}, [conflict(target, "org_id", f"[org:{target['org_id']}]", f"[org:{org_id}]")]
        if target is None:
            target = await open_row()
            # A number fills the open row only when its source supersedes the row's; else it is its own fact.
            if target is not None and not (target["status"] == "check_blocked"
                                           or may_overwrite(target["source_type"], tier.source_type)):
                differs = target["status"] != rec.status
                return await insert([conflict(target, "status", target["status"], rec.status)] if differs else [])
    elif rec.status == "applied":
        # An application never lands on a number; a live registration of the type is a conflict with it.
        numbered = await (
            await conn.execute(head + "org_id = %s AND id_type = %s AND id_value IS NOT NULL AND is_current "
                               "AND status IN ('registered', 'provisional') ORDER BY id FOR UPDATE",
                               (org_id, rec.id_type))
        ).fetchall()
        found = [conflict(r, "status", f"{r['status']} ({r['id_value']})", "applied") for r in numbered]
        stronger = next((r for r in numbered if outranks(r["source_type"], tier.source_type)), None)
        if stronger is not None:
            # The registration supersedes the application; only its acknowledgement number may fill a blank.
            if stronger["application_ref"] is None and rec.application_ref:
                await conn.execute("UPDATE org_identifiers SET application_ref = %s WHERE id = %s",
                                   (rec.application_ref, stronger["id"]))
                return "updated", {"application_ref": {"old": None, "new": rec.application_ref}}, found
            return "matched", {}, found
        target = await open_row()
        if target is None:
            return await insert(found)
        pending = found
    else:
        target = await open_row()
        if target is None:
            # A status with no number is about the one current registration of that type, if there is one.
            rows = await (
                await conn.execute(head + "org_id = %s AND id_type = %s AND is_current ORDER BY id LIMIT 2 "
                                   "FOR UPDATE", (org_id, rec.id_type))
            ).fetchall()
            target = rows[0] if len(rows) == 1 else None
    if target is None:
        return await insert([])

    if target["id_value"] is not None:
        proposed["id_value"] = None     # found by its number, case-insensitively: the spelling is not news
    if rec.status == "check_blocked":
        # A check nobody could make confirms nothing: no status, tier, method or provenance moves.
        same = target["status"] == "check_blocked"
        return "matched", {}, pending + ([] if same else [conflict(target, "status", target["status"],
                                                                   "check_blocked")])
    if target["status"] == "check_blocked":
        # A stored blocked check knew nothing, so any real finding takes the row whatever its tier.
        write = {c: {"old": plain(target[c]), "new": plain(v)} for c, v in proposed.items()
                 if v is not None and (target[c] is None or diff_row({c: target[c]}, {c: v}))}
        retier = {"source_type": {"old": target["source_type"], "new": tier.source_type},
                  "evidence": {"old": target["evidence"], "new": tier.evidence}}
        kept: list[tuple[str, Any, Any]] = []
    else:
        write, kept = ranked_changes(dict(target), proposed, target["source_type"], tier.source_type)
        retier = takes_row(target, proposed, tier)
    conflicts = pending + [conflict(target, c, old, new) for c, old, new in kept]
    if not write and not retier:
        return "matched", {}, conflicts
    sets = {c: proposed[c] for c in write}
    if retier:
        sets.update({c: v for c, v in provenance.items() if v is not None})
        sets.update(source_type=tier.source_type, evidence=tier.evidence)
    await conn.execute(
        f"UPDATE org_identifiers SET {', '.join(f'{c} = %s' for c in sets)}, "
        "document_id = coalesce(document_id, %s) WHERE id = %s",
        (*sets.values(), document_id, target["id"]),
    )
    return "updated", {**write, **retier}, conflicts


async def write_org_financials(
    conn: Any, rec: OrgFinancialsRecord, org_id: int, document_id: int | None
) -> tuple[str, dict, list[Conflict]]:
    """One fiscal year on UNIQUE (org_id, fiscal_year). A directory's income never replaces the audited one."""
    return await upsert_ranked(
        conn, "org_financials", {"org_id": org_id, "fiscal_year": rec.fiscal_year}, ORG_FINANCIALS_VALUES,
        {c: getattr(rec, c) for c in (*ORG_FINANCIALS_VALUES, "source_url", "source_name", "fetched_at",
                                      "as_of")},
        Tier.of(rec), document_id, row=f"[org:{org_id}] {rec.fiscal_year}",
    )


async def write_org_location(
    conn: Any, rec: OrgLocationRecord, org_id: int, *, location_id: int, document_id: int | None,
    program_id: int | None = None,
) -> tuple[str, dict, list[Conflict]]:
    return await upsert_ranked(
        conn, "org_locations", {"org_id": org_id, "location_id": location_id}, ORG_LOCATION_VALUES,
        {"role": rec.role, "note": rec.note, "program_id": program_id, "source_url": rec.source_url,
         "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of},
        Tier.of(rec), document_id, row=f"[org:{org_id}] location {location_id}",
    )


async def set_registered_location(conn: Any, owner: Owner, location_id: int) -> bool:
    """registered_location_id from a 'registered' place finding: fill-only and untiered, unlike the ranked
    columns beside it. A planned save writes nothing."""
    if (gate := GATE.get()) and gate.plan:
        return False
    table = "orgs" if owner.column == "org_id" else "funders"
    row = await (
        await conn.execute(
            f"UPDATE {table} SET registered_location_id = %s "
            "WHERE id = %s AND registered_location_id IS NULL RETURNING id",
            (location_id, owner.id),
        )
    ).fetchone()
    return row is not None
