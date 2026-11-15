"""Writes a funder, its CSR years and the fact tables a funder (and, by Owner, an org) holds."""

from __future__ import annotations

import json
from typing import Any

from app.ingest.catalog.matcher import Match
from app.ingest.catalog.rows import (
    FunderCsrYearRecord,
    FunderRecord,
)
from app.ingest.catalog.writer import (
    CLASSIFICATION,
    EXTRACTOR_TAGGER,
    GATE,
    NOT_FACTS,
    UNWRITTEN,
    Conflict,
    Owner,
    Tier,
    diff_row,
    ensure_document,
    free_slug,
    new_aliases,
    outranks,
    plain,
    ranked_values,
    sink_conflicts,
    slugify,
    upsert,
    upsert_ranked,
)

# Columns a re-import may overwrite on an existing funder. Everything else on the
# row was either hand-vetted or set by a different source, so an importer leaves it.
FUNDER_UPDATABLE = (
    "funder_type", "website", "section_135_bound", "parent_id", "cin",
    "intake_mode", "funds_external", "typical_duration_months", "grant_size_min", "grant_size_max",
    "legal_form", "founded_year", "registered_address",
    "source_url", "source_name", "fetched_at", "as_of", "content_hash", "extractor_version",
)


# All ten statutory items, not the four this used to carry. The researcher
# collected the other six and promotion dropped them without a word.
CSR_YEAR_UPDATABLE = (
    "prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred",
    "spent_on_projects", "admin_overheads", "impact_assessment_cost", "excess_spent",
    "local_area_spent", "impact_assessment_done", "section_135_applicable", "notes",
    "source_url", "source_name", "fetched_at", "as_of",
)


async def write_funder(
    conn: Any, rec: FunderRecord, match: Match, *, parent_id: int | None = None
) -> tuple[str, int, dict]:
    """Returns (status, funder_id, changes). Status is added | updated | matched.

    parent_id is resolved by the caller, which can report a parent it could not find; this writer
    only stores what it is given. Aliases are appended, never replaced: a spelling one source used
    is still a way to find this funder.
    """
    proposed = {
        "funder_type": rec.funder_type, "website": rec.website,
        "section_135_bound": rec.section_135_bound, "parent_id": parent_id, "cin": rec.cin,
        "intake_mode": rec.intake_mode, "funds_external": rec.funds_external,
        "typical_duration_months": rec.typical_duration_months,
        "grant_size_min": rec.grant_size_min, "grant_size_max": rec.grant_size_max,
        "legal_form": rec.legal_form, "founded_year": rec.founded_year,
        "registered_address": rec.registered_address,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    gate = GATE.get()
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT id, name, aliases, {', '.join(FUNDER_UPDATABLE)} FROM funders WHERE id = %s",
                (match.entity_id,),
            )
        ).fetchone()
        changes = diff_row({c: existing[c] for c in FUNDER_UPDATABLE}, proposed)
        if changes and gate and gate.on_change(
            "funders", {"name": existing["name"]}, dict(existing), changes, proposed
        ) != "update":
            changes = {}
        held = list(existing["aliases"] or [])
        added = new_aliases(held, rec.aliases, existing["name"])
        if not changes and not added:
            return "matched", match.entity_id, {}
        if gate and gate.plan:
            return "updated", match.entity_id, changes
        sets = [f"{c} = %s" for c in changes]
        values = [proposed[c] for c in changes]
        if added:
            sets.append("aliases = aliases || %s::text[]")
            values.append(added)
            changes["aliases"] = {"old": held, "new": [*held, *added]}
        await conn.execute(
            f"UPDATE funders SET {', '.join(sets)} WHERE id = %s", (*values, match.entity_id)
        )
        return "updated", match.entity_id, changes

    if gate:
        gate._item(5, "funders", {"name": rec.name}, outcome="planned" if gate.plan else "written",
                   new={c: plain(v) for c, v in proposed.items() if v is not None and c not in NOT_FACTS})
        if gate.plan:
            return "added", UNWRITTEN, {"name": {"old": None, "new": rec.name}}
    slug = await free_slug(conn, slugify(rec.name))
    row = await (
        await conn.execute(
            "INSERT INTO funders (slug, name, funder_type, website, section_135_bound, parent_id, cin, "
            "aliases, intake_mode, funds_external, typical_duration_months, grant_size_min, "
            "grant_size_max, legal_form, founded_year, registered_address, registry_status, source_url, "
            "source_name, fetched_at, as_of, content_hash, extractor_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', "
            "%s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.funder_type, rec.website, rec.section_135_bound, parent_id, rec.cin,
             new_aliases([], rec.aliases, rec.name), rec.intake_mode, rec.funds_external,
             rec.typical_duration_months, rec.grant_size_min, rec.grant_size_max,
             rec.legal_form, rec.founded_year, rec.registered_address, rec.source_url, rec.source_name, rec.fetched_at, rec.as_of,
             rec.content_hash, rec.extractor_version),
        )
    ).fetchone()
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}


async def cin_holder(conn: Any, cin: str) -> dict | None:
    """The funder already holding this CIN, if any. funders.cin is UNIQUE."""
    return await (
        await conn.execute("SELECT id, name FROM funders WHERE cin = %s", (cin,))
    ).fetchone()


async def write_csr_year(
    conn: Any, rec: FunderCsrYearRecord, funder_id: int, document_id: int | None
) -> tuple[str, dict]:
    proposed = {
        "prescribed_csr": rec.prescribed_csr, "total_spent": rec.total_spent,
        "average_net_profit": rec.average_net_profit, "unspent_transferred": rec.unspent_transferred,
        "spent_on_projects": rec.spent_on_projects, "admin_overheads": rec.admin_overheads,
        "impact_assessment_cost": rec.impact_assessment_cost, "excess_spent": rec.excess_spent,
        "local_area_spent": rec.local_area_spent,
        "impact_assessment_done": rec.impact_assessment_done,
        "section_135_applicable": rec.section_135_applicable, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    existing = await (
        await conn.execute(
            f"SELECT {', '.join(CSR_YEAR_UPDATABLE)} FROM funder_csr_years "
            "WHERE funder_id = %s AND fiscal_year = %s",
            (funder_id, rec.fiscal_year),
        )
    ).fetchone()
    gate = GATE.get()
    key = {"funder_id": funder_id, "fiscal_year": rec.fiscal_year}
    if existing is None:
        cols = [c for c in CSR_YEAR_UPDATABLE if proposed[c] is not None]
        if gate:
            gate._item(5, "funder_csr_years", key, outcome="planned" if gate.plan else "written",
                       new={c: plain(proposed[c]) for c in cols if c not in NOT_FACTS})
            if gate.plan:
                return "added", {}
        await conn.execute(
            f"INSERT INTO funder_csr_years (funder_id, fiscal_year, document_id, {', '.join(cols)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(cols))})",
            (funder_id, rec.fiscal_year, document_id, *[proposed[c] for c in cols]),
        )
        return "added", {c: {"old": None, "new": plain(proposed[c])} for c in cols}
    changes = diff_row(dict(existing), proposed)
    if not changes:
        if gate:
            gate.same += 1
        return "matched", {}
    if gate:
        verdict = gate.on_change("funder_csr_years", key, dict(existing), changes, proposed)
        if verdict != "update":
            return ("kept" if verdict == "keep" else "asked"), {}
        if gate.plan:
            return "updated", changes
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE funder_csr_years SET {sets}, document_id = coalesce(document_id, %s) "
        "WHERE funder_id = %s AND fiscal_year = %s",
        (*[proposed[c] for c in changes], document_id, funder_id, rec.fiscal_year),
    )
    return "updated", changes


def _json(v: Any) -> str:
    return json.dumps(v, default=str)


# funder_activity's UNIQUE NULLS NOT DISTINCT key, in its order. `kind` is part of it, so a spend
# line and a partner line that agree on everything else are two lines (0031).
FUNDER_ACTIVITY_KEY = ("funder_id", "kind", "fiscal_year", "program_id", "csr_sector_id",
                       "state_location_id", "location_id", "designation", "project_name", "partner_name")


# is_public is deliberately absent: a new line takes the column's DEFAULT true and no writer updates
# it, so a line a person marked internal (D14) stays internal through every re-promote.
FUNDER_ACTIVITY_UPDATABLE = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note",
                             "name_as_printed", "implementation_mode", "partner_canonical",
                             "partner_csr1", "partner_kind", "outlay", "amount", "project_count",
                             "is_ongoing", "notes", "source_url", "source_name", "fetched_at", "as_of",
                             "start_date", "end_date", "relationship_status", "partner_org_id",
                             "source_type", "evidence")


FUNDER_LOCATION_KEY = ("funder_id", "location_id")


FUNDER_LOCATION_UPDATABLE = ("role", "note", "source_url", "source_name", "fetched_at", "as_of")


PROGRAM_KEY = ("funder_id", "name")


PROGRAM_UPDATABLE = ("description", "status", "start_date", "end_date", "parent_id", "kind",
                     "is_enabler", "source_url", "source_name", "fetched_at", "as_of",
                     "content_hash", "extractor_version")


METRIC_KEY = ("funder_id", "name", "period", "program_id")


METRIC_UPDATABLE = ("value", "target", "unit", "stage", "method", "is_self_reported",
                    "baseline", "comparison_value", "chain_key", "sequence", "location_id",
                    "notes", "source_url", "source_name", "fetched_at", "as_of")


CONTACT_KEY = ("funder_id", "name", "role")


CONTACT_UPDATABLE = ("kind", "email", "is_public", "notes",
                     "source_url", "source_name", "fetched_at", "as_of",
                     "content_hash", "extractor_version")


def _activity_refusal(key: dict[str, Any], row: dict[str, Any]) -> str | None:
    """funder_activity's CHECKs, asked before the write: a CheckViolation would abort the whole promotion."""
    kind = key["kind"]
    if kind == "spend" and row.get("amount") is None:
        return "a spend line needs an amount"
    if kind == "footprint" and key["location_id"] is None and key["state_location_id"] is None:
        return "a footprint line needs a place"
    if kind == "partner" and key["partner_name"] is None:
        return "a partner line needs the partner's name"
    if kind == "programme" and (key["program_id"] is None or row.get("amount") is None):
        return "a programme line needs a resolved programme and an amount"
    if row.get("domain_tag_id") is not None and row.get("classified_by") is None:
        return "a domain needs classified_by, saying what it rests on"
    return None


async def _write_activity(
    conn: Any, key: dict[str, Any], proposed: dict[str, Any], document_id: int | None
) -> tuple[str, dict]:
    """One funder_activity line. A classification a person confirmed is never re-inferred (D11).
    Returns ("held", {"reason": ...}) for a line the table's CHECKs would refuse."""
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    row = await (
        await conn.execute(
            f"SELECT classification_confirmed, amount, classified_by FROM funder_activity WHERE {where}",
            tuple(key.values()),
        )
    ).fetchone()
    if row and row["classification_confirmed"]:
        proposed = {c: v for c, v in proposed.items() if c not in CLASSIFICATION}
    # A proposed NULL never erases, so the row as it will stand is the stored one under the proposal.
    standing = {**(dict(row) if row else {}), **{c: v for c, v in proposed.items() if v is not None}}
    if why := _activity_refusal(key, standing):
        return "held", {"reason": why}
    return await upsert(conn, "funder_activity", key, FUNDER_ACTIVITY_UPDATABLE, proposed, document_id)


def _activity_key(funder_id: int, kind: str, fiscal_year: str, **ids: Any) -> dict[str, Any]:
    key = dict.fromkeys(FUNDER_ACTIVITY_KEY)
    key.update(funder_id=funder_id, kind=kind, fiscal_year=fiscal_year, **ids)
    return key


async def write_csr_spend(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, state_id: int | None,
    district_id: int | None, csr_sector_id: int | None, domain_id: int | None,
    theme_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(
        funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
        csr_sector_id=csr_sector_id, state_location_id=state_id, location_id=district_id,
        designation=rec.designation, project_name=rec.project_name, partner_name=rec.partner_name,
    )
    proposed = {
        "domain_tag_id": domain_id, "theme_tag_id": theme_id,
        "classified_by": rec.classified_by, "classification_note": rec.classification_note,
        "implementation_mode": rec.implementation_mode, "partner_csr1": rec.partner_csr1,
        "outlay": rec.outlay, "amount": rec.amount, "project_count": rec.project_count,
        "is_ongoing": rec.is_ongoing, "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_footprint(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
    state_id: int | None, district_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                        state_location_id=state_id, location_id=district_id)
    proposed = {
        "name_as_printed": rec.name_as_printed, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_funder_location(
    conn: Any, rec: Any, funder_id: int, *, location_id: int, document_id: int | None
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "location_id": location_id}
    proposed = {
        "role": rec.role, "note": rec.note, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await upsert(
        conn, "funder_locations", key, FUNDER_LOCATION_UPDATABLE, proposed, document_id
    )


# What an organisation's research may not change on a funder's line; a difference is a conflict.
PARTNER_GUARDED = ("amount", "start_date", "end_date", "relationship_status", "source_url")


def _appended(stored: str | None, incoming: str | None) -> str | None:
    """Notes only grow: incoming lines not already stored go after the stored ones."""
    have = {ln.strip() for ln in (stored or "").splitlines()}
    fresh = [ln for ln in (incoming or "").splitlines() if ln.strip() and ln.strip() not in have]
    if not fresh:
        return None
    return "\n".join([stored, *fresh]) if stored else "\n".join(fresh)


async def write_partner(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None,
    partner_org_id: int | None = None, fill_only: bool = False, conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    """One partner line; a grant is one, so two projects with one partner in a year are two lines.
    fill_only (an organisation's research) fills blanks and reports a differing value as a conflict."""
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                        project_name=rec.project_name, partner_name=rec.partner_name)
    proposed = {
        "partner_canonical": rec.partner_canonical or rec.partner_name,
        "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1, "partner_org_id": partner_org_id,
        "outlay": rec.outlay, "amount": rec.amount, "start_date": rec.start_date, "end_date": rec.end_date,
        "relationship_status": rec.relationship_status, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "source_type": rec.source_type, "evidence": rec.evidence_tier,
    }
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    stored = await (
        await conn.execute(f"SELECT id, {', '.join(proposed)} FROM funder_activity WHERE {where}",
                           tuple(key.values()))
    ).fetchone()
    if stored:
        proposed["notes"] = _appended(stored["notes"], rec.notes)
        if rec.source_type and outranks(stored["source_type"], rec.source_type):
            proposed["source_type"] = proposed["evidence"] = None
        for c in (c for c in proposed if fill_only and c != "notes" and stored[c] is not None):
            if c in PARTNER_GUARDED and diff_row({c: stored[c]}, {c: proposed[c]}):
                sink_conflicts(conflicts, [Conflict(
                    "funder_activity", f"[activity:{stored['id']}] partner {rec.partner_name!r} {rec.fiscal_year}",
                    c, plain(stored[c]), None, stored["source_url"], plain(proposed[c]),
                    getattr(rec, "source_type", None) or "unranked", rec.source_url)])
            proposed[c] = None
    return await _write_activity(conn, key, proposed, document_id)


async def write_programme_spend(
    conn: Any, rec: Any, funder_id: int, *, program_id: int, domain_id: int | None,
    theme_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id)
    proposed = {
        "domain_tag_id": domain_id, "theme_tag_id": theme_id, "classified_by": rec.classified_by,
        "classification_note": rec.classification_note, "amount": rec.amount, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_program(
    conn: Any, rec: Any, owner: Owner, *, parent_id: int | None, document_id: int | None,
    conflicts: list[Conflict] | None = None,
) -> tuple[str, int, dict]:
    """Returns (status, program_id, changes) — the id is needed by every fact
    that names a programme."""
    key = {owner.column: owner.id, "name": rec.name}
    proposed = {
        "description": rec.description, "status": rec.status, "start_date": rec.start_date,
        "end_date": rec.end_date, "parent_id": parent_id, "kind": rec.program_kind,
        "is_enabler": rec.is_enabler, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await upsert_ranked(
            conn, "programs", key, ranked_values(PROGRAM_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] programme {rec.name!r}",
        )
        sink_conflicts(conflicts, found)
    else:
        status, changes = await upsert(
            conn, "programs", key, PROGRAM_UPDATABLE, proposed, document_id
        )
    row = await (
        await conn.execute(
            f"SELECT id FROM programs WHERE {owner.column} = %s AND name = %s",
            (owner.id, rec.name),
        )
    ).fetchone()
    if row is None:
        # Unwritten: planned (a placeholder its facts can key on), or waiting on a person (None).
        gate = GATE.get()
        return status, UNWRITTEN if gate and gate.plan and status in ("added", "updated") else None, changes
    return status, row["id"], changes


async def write_metric(
    conn: Any, rec: Any, owner: Owner, *, program_id: int | None,
    location_id: int | None, document_id: int | None, conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    key = {owner.column: owner.id, "name": rec.name, "period": rec.period,
           "program_id": program_id}
    proposed = {
        "value": rec.value, "target": rec.target, "unit": rec.unit, "stage": rec.stage,
        "method": rec.method, "is_self_reported": rec.is_self_reported,
        "baseline": rec.baseline, "comparison_value": rec.comparison_value,
        "chain_key": rec.chain_key, "sequence": rec.sequence, "location_id": location_id,
        "notes": rec.notes, "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await upsert_ranked(
            conn, "metrics", key, ranked_values(METRIC_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] metric {rec.name!r} {rec.period or ''}".strip(),
        )
        sink_conflicts(conflicts, found)
        return status, changes
    return await upsert(conn, "metrics", key, METRIC_UPDATABLE, proposed, document_id)


async def write_contact(
    conn: Any, rec: Any, owner: Owner, *, document_id: int | None,
    conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    key = {owner.column: owner.id, "name": rec.name, "role": rec.role}
    proposed = {
        "kind": rec.contact_kind, "email": rec.email,
        # A shared mailbox the funder published is public by definition; the
        # column defaults to false and nothing else here sets it.
        "is_public": True if rec.email else None,
        "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await upsert_ranked(
            conn, "contacts", key, ranked_values(CONTACT_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] contact {rec.name!r}",
        )
        sink_conflicts(conflicts, found)
        return status, changes
    return await upsert(conn, "contacts", key, CONTACT_UPDATABLE, proposed, document_id)


RFP_KEY = ("funder_id", "title", "deadline")


RFP_UPDATABLE = ("url", "status", "amount_min", "amount_max", "eligibility",
                 "source_url", "source_name", "fetched_at", "as_of",
                 "content_hash", "extractor_version")


async def write_rfp(
    conn: Any, rec: Any, funder_id: int, *, location_id: int | None,
    tag_id: int | None, document_id: int | None,
) -> tuple[str, int, dict]:
    """A call for proposals, plus where it applies and what theme it is for.

    Returns (status, rfp_id, changes). An RFP with no place attached cannot be
    matched to a client, so rfp_locations and rfp_tags are written here rather
    than left for later.
    """
    key = {"funder_id": funder_id, "title": rec.title, "deadline": rec.deadline}
    proposed = {
        "url": rec.url, "status": rec.status,
        "amount_min": rec.amount_min, "amount_max": rec.amount_max,
        "eligibility": _json({"requirements": rec.eligibility}),
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    status, changes = await upsert(conn, "rfps", key, RFP_UPDATABLE, proposed, document_id)
    gate = GATE.get()
    if gate and (gate.plan or status in ("asked", "skipped", "kept", "held")):
        return status, None, changes
    row = await (
        await conn.execute(
            "SELECT id FROM rfps WHERE funder_id = %s AND title = %s "
            "AND deadline IS NOT DISTINCT FROM %s",
            (funder_id, rec.title, rec.deadline),
        )
    ).fetchone()
    rfp_id = row["id"]

    if location_id is not None:
        await conn.execute(
            "INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, "
            "fetched_at) VALUES (%s, %s, 'funds', %s, %s, %s) "
            "ON CONFLICT (rfp_id, location_id) DO NOTHING",
            (rfp_id, location_id, rec.source_url, rec.source_name, rec.fetched_at),
        )
    if tag_id is not None:
        await conn.execute(
            "INSERT INTO rfp_tags (rfp_id, tag_id, role, is_inferred, tagged_by) "
            "VALUES (%s, %s, 'primary', true, %s) ON CONFLICT (rfp_id, tag_id) DO NOTHING",
            (rfp_id, tag_id, EXTRACTOR_TAGGER),
        )
    return status, rfp_id, changes


async def write_eligibility_document(conn: Any, rec: Any, funder_id: int) -> tuple[int, str]:
    """The funder's standing eligibility as one documents row, text verbatim (D3).

    Keyed by ensure_document on (source_url, 'funder_eligibility', funder). The text follows the newest
    research, and is_public follows the funder (D14): a hidden funder's guideline is staff-only.
    """
    gate = GATE.get()
    if gate and gate.plan:
        return 0, "planned"
    document_id, status = await ensure_document(
        conn, rec, owner=Owner.funder(funder_id), doc_type=rec.doc_type
    )
    content = rec.content_md()
    changed = await (
        await conn.execute(
            "UPDATE documents d SET content_md = %s, title = %s, as_of = coalesce(%s, d.as_of), "
            "fetched_at = %s, is_public = f.registry_status <> 'hidden' "
            "FROM funders f WHERE d.id = %s AND f.id = d.funder_id "
            "AND (d.content_md IS DISTINCT FROM %s OR d.is_public IS DISTINCT FROM "
            "(f.registry_status <> 'hidden')) RETURNING d.id",
            (content, rec.title, rec.as_of, rec.fetched_at, document_id, content),
        )
    ).fetchone()
    if status == "matched" and changed is not None:
        status = "updated"
    return document_id, status


async def write_funder_tag(conn: Any, funder_id: int, tag_id: int, *, note: str | None) -> None:
    """A theme this funder actually spends on, so field-8 questions can be
    answered from one place instead of aggregated over spend rows.

    is_inferred is always true: the clause was chosen from the funder's own
    wording by a keyword table, and the row should say that rather than read
    as the funder's own classification.
    """
    gate = GATE.get()
    if gate and gate.plan:
        return
    await conn.execute(
        "INSERT INTO funder_tags (funder_id, tag_id, role, is_inferred, tagged_by, note) "
        "VALUES (%s, %s, 'primary', true, %s, %s) "
        "ON CONFLICT (funder_id, tag_id) DO NOTHING",
        (funder_id, tag_id, EXTRACTOR_TAGGER, note),
    )
