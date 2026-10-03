"""The only code that writes imported data. Fixed SQL, never model-authored."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ingest.matcher import Match
from app.ingest.records import FunderCsrYearRecord, FunderRecord, NewsMentionRecord

# Columns a re-import may overwrite on an existing funder. Everything else on the
# row was either hand-vetted or set by a different source, so an importer leaves it.
FUNDER_UPDATABLE = (
    "funder_type", "website", "section_135_bound", "parent_id",
    "source_url", "source_name", "fetched_at", "as_of", "content_hash", "extractor_version",
)
# All ten statutory items, not the four this used to carry. The researcher
# collected the other six and promotion dropped them without a word.
CSR_YEAR_UPDATABLE = (
    "prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred",
    "spent_on_projects", "admin_overheads", "impact_assessment_cost", "excess_spent",
    "impact_assessment_done", "section_135_applicable", "notes",
    "source_url", "source_name", "fetched_at", "as_of",
)


# Recorded on any tag we attach, because a Schedule VII clause chosen from a
# funder's own wording is an inference and the row should say so.
EXTRACTOR_TAGGER = "sangam-import"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def _diff(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Columns whose value actually changes; a proposed NULL never erases a value."""
    out: dict[str, dict[str, Any]] = {}
    for col, new in proposed.items():
        if new is None:
            continue
        old = existing.get(col)
        # A jsonb column reads back as a dict or list while the proposed value
        # is the JSON string we are about to send, so a direct comparison is
        # always unequal and every re-run looks like an edit.
        if isinstance(old, dict | list) and isinstance(new, str):
            try:
                same = old == json.loads(new)
            except ValueError:
                same = False
        elif isinstance(old, str) and isinstance(new, str):
            same = old.strip() == new.strip()
        elif old is not None and isinstance(new, int | float) and not isinstance(new, bool):
            # Relative, not absolute: an amount in crore is ~1e8, where a
            # 1e-9 absolute epsilon is far below float precision and every
            # comparison reads as a change.
            old_f, new_f = float(old), float(new)
            same = abs(old_f - new_f) <= 1e-9 * max(1.0, abs(old_f), abs(new_f))
        else:
            same = old == new
        if not same:
            out[col] = {"old": _plain(old), "new": _plain(new)}
    return out


def _plain(v: Any) -> Any:
    return v if v is None or isinstance(v, str | int | float | bool) else str(v)


async def ensure_document(
    conn: Any, rec: Any, *, funder_id: int | None, doc_type: str,
    storage_path: str | None = None, content_hash: str | None = None,
) -> tuple[int, str]:
    """One documents row per source URL, so many facts can cite one report.

    Returns (id, added | updated | matched), like the other writers here. The
    archive columns backfill onto a row that predates archiving, and only where
    the row is empty - a re-promote never overwrites what is already recorded.
    """
    row = await (
        await conn.execute(
            "SELECT id, storage_path, content_hash FROM documents WHERE source_url = %s",
            (rec.source_url,),
        )
    ).fetchone()
    if row:
        # Column names come from this dict, never from a caller; only values
        # are parameterised. Same rule as _upsert.
        fill = {c: v for c, v in
                (("storage_path", storage_path), ("content_hash", content_hash))
                if v and not row[c]}
        if not fill:
            return row["id"], "matched"
        sets = ", ".join(f"{c} = %s" for c in fill)
        await conn.execute(
            f"UPDATE documents SET {sets} WHERE id = %s", (*fill.values(), row["id"])
        )
        return row["id"], "updated"
    row = await (
        await conn.execute(
            "INSERT INTO documents (funder_id, title, doc_type, source_url, source_name, "
            "fetched_at, as_of, storage_path, content_hash, is_public, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, 'read') RETURNING id",
            (funder_id, getattr(rec, "title", None), doc_type, rec.source_url,
             rec.source_name, rec.fetched_at, rec.as_of, storage_path, content_hash),
        )
    ).fetchone()
    return row["id"], "added"


async def write_funder(
    conn: Any, rec: FunderRecord, match: Match, *, parent_id: int | None = None
) -> tuple[str, int, dict]:
    """Returns (status, funder_id, changes). Status is added | updated | matched.

    parent_id is resolved by the caller, which can report a parent it could not
    find; this writer only stores what it is given.
    """
    proposed = {
        "funder_type": rec.funder_type, "website": rec.website,
        "section_135_bound": rec.section_135_bound, "parent_id": parent_id,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT {', '.join(FUNDER_UPDATABLE)} FROM funders WHERE id = %s", (match.funder_id,)
            )
        ).fetchone()
        changes = _diff(dict(existing), proposed)
        if not changes:
            return "matched", match.funder_id, {}
        sets = ", ".join(f"{c} = %s" for c in changes)
        await conn.execute(
            f"UPDATE funders SET {sets} WHERE id = %s",
            (*[proposed[c] for c in changes], match.funder_id),
        )
        await _write_identifiers(conn, match.funder_id, rec)
        return "updated", match.funder_id, changes

    slug = await _free_slug(conn, slugify(rec.name))
    row = await (
        await conn.execute(
            "INSERT INTO funders (slug, name, funder_type, website, section_135_bound, "
            "parent_id, registry_status, source_url, source_name, fetched_at, as_of, "
            "content_hash, extractor_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'placeholder', %s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.funder_type, rec.website, rec.section_135_bound, parent_id,
             rec.source_url, rec.source_name, rec.fetched_at, rec.as_of,
             rec.content_hash, rec.extractor_version),
        )
    ).fetchone()
    await _write_identifiers(conn, row["id"], rec)
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}


async def _free_slug(conn: Any, base: str) -> str:
    slug, n = base, 2
    while await (await conn.execute("SELECT 1 FROM funders WHERE slug = %s", (slug,))).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


async def _write_identifiers(conn: Any, funder_id: int, rec: FunderRecord) -> None:
    for id_type, id_value in rec.identifiers.items():
        await conn.execute(
            "INSERT INTO funder_identifiers (funder_id, id_type, id_value, source_url, source_name, "
            "fetched_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id_type, id_value) DO NOTHING",
            (funder_id, id_type, id_value, rec.source_url, rec.source_name, rec.fetched_at),
        )


async def write_csr_year(
    conn: Any, rec: FunderCsrYearRecord, funder_id: int, document_id: int | None
) -> tuple[str, dict]:
    proposed = {
        "prescribed_csr": rec.prescribed_csr, "total_spent": rec.total_spent,
        "average_net_profit": rec.average_net_profit, "unspent_transferred": rec.unspent_transferred,
        "spent_on_projects": rec.spent_on_projects, "admin_overheads": rec.admin_overheads,
        "impact_assessment_cost": rec.impact_assessment_cost, "excess_spent": rec.excess_spent,
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
    if existing is None:
        cols = [c for c in CSR_YEAR_UPDATABLE if proposed[c] is not None]
        await conn.execute(
            f"INSERT INTO funder_csr_years (funder_id, fiscal_year, document_id, {', '.join(cols)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(cols))})",
            (funder_id, rec.fiscal_year, document_id, *[proposed[c] for c in cols]),
        )
        return "added", {c: {"old": None, "new": _plain(proposed[c])} for c in cols}
    changes = _diff(dict(existing), proposed)
    if not changes:
        return "matched", {}
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE funder_csr_years SET {sets}, document_id = coalesce(document_id, %s) "
        "WHERE funder_id = %s AND fiscal_year = %s",
        (*[proposed[c] for c in changes], document_id, funder_id, rec.fiscal_year),
    )
    return "updated", changes


async def write_news_mention(
    conn: Any, rec: NewsMentionRecord, funder_id: int | None
) -> tuple[str, dict]:
    existing = await (
        await conn.execute("SELECT id, funder_id FROM news_mentions WHERE url = %s", (rec.url,))
    ).fetchone()
    if existing is None:
        await conn.execute(
            "INSERT INTO news_mentions (url, title, seendate, domain, topic, funder_id, summary, "
            "source_name, fetched_at, review_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
            (rec.url, rec.title, rec.seendate, rec.domain, rec.topic, funder_id,
             rec.summary, rec.source_name, rec.fetched_at),
        )
        return "added", {"url": {"old": None, "new": rec.url}}
    if funder_id and existing["funder_id"] is None:
        await conn.execute("UPDATE news_mentions SET funder_id = %s WHERE id = %s",
                           (funder_id, existing["id"]))
        return "updated", {"funder_id": {"old": None, "new": funder_id}}
    return "matched", {}


async def queue_resolution(
    conn: Any, *, raw_name: str, kind: str, match: Match, source: str, rec: Any
) -> int:
    """A name we will not merge on our own. The next run resolves it once accepted."""
    row = await (
        await conn.execute(
            "INSERT INTO resolution_queue (raw_name, entity_kind, candidates, source, context, "
            "source_url, source_name, fetched_at, as_of) "
            "VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s) "
            "ON CONFLICT (entity_kind, raw_name, source) DO UPDATE SET candidates = EXCLUDED.candidates "
            "RETURNING id",
            (raw_name, kind, _json(match.candidates), source,
             _json({"method": match.method, "score": match.score}),
             rec.source_url, rec.source_name, rec.fetched_at, rec.as_of),
        )
    ).fetchone()
    return row["id"]


def _json(v: Any) -> str:
    return json.dumps(v, default=str)


# --- The funder-side fact tables -------------------------------------------
#
# Each follows write_csr_year: an <X>_UPDATABLE allowlist, a SELECT on the
# table's own natural key, _diff, then insert or update. The keys are the
# UNIQUE NULLS NOT DISTINCT constraints the schema already declares, so a
# re-import updates a row rather than growing a second one.

CSR_SPEND_KEY = ("funder_id", "fiscal_year", "program_id", "csr_sector_id",
                 "state_location_id", "district_location_id", "designation", "project_name")
CSR_SPEND_UPDATABLE = ("implementing_agency", "agency_csr1", "via_agency", "is_ongoing",
                       "amount", "project_count", "notes", "source_url", "source_name",
                       "fetched_at", "as_of")
FOOTPRINT_KEY = ("funder_id", "program_id", "fiscal_year", "location_id")
FOOTPRINT_UPDATABLE = ("name_as_printed", "notes", "source_url", "source_name",
                       "fetched_at", "as_of")
FUNDER_LOCATION_KEY = ("funder_id", "location_id")
FUNDER_LOCATION_UPDATABLE = ("role", "note", "source_url", "source_name", "fetched_at", "as_of")
PARTNER_KEY = ("funder_id", "program_id", "fiscal_year", "partner_name")
PARTNER_UPDATABLE = ("partner_canonical", "partner_kind", "partner_csr1", "notes",
                     "source_url", "source_name", "fetched_at", "as_of")
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


async def _upsert(
    conn: Any, table: str, key: dict[str, Any], updatable: tuple[str, ...],
    proposed: dict[str, Any], document_id: int | None,
) -> tuple[str, dict]:
    """Find the row by its natural key, then insert or diff-update it.

    Table and column names come from the module constants above, never from a
    caller; only values are parameterised.
    """
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    existing = await (
        await conn.execute(
            f"SELECT {', '.join(updatable)} FROM {table} WHERE {where}", tuple(key.values())
        )
    ).fetchone()

    if existing is None:
        cols = list(key) + [c for c in updatable if proposed.get(c) is not None]
        values = list(key.values()) + [proposed[c] for c in cols[len(key):]]
        if document_id is not None:
            cols.append("document_id")
            values.append(document_id)
        await conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
            tuple(values),
        )
        return "added", {c: {"old": None, "new": _plain(v)} for c, v in zip(cols, values, strict=True)}

    changes = _diff(dict(existing), proposed)
    if not changes:
        return "matched", {}
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE {table} SET {sets}, document_id = coalesce(document_id, %s) WHERE {where}",
        (*[proposed[c] for c in changes], document_id, *key.values()),
    )
    return "updated", changes


async def write_csr_spend(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
    state_id: int | None, district_id: int | None, csr_sector_id: int | None,
    document_id: int | None,
) -> tuple[str, dict]:
    key = {
        "funder_id": funder_id, "fiscal_year": rec.fiscal_year, "program_id": program_id,
        "csr_sector_id": csr_sector_id, "state_location_id": state_id,
        "district_location_id": district_id, "designation": rec.designation,
        "project_name": rec.project_name,
    }
    proposed = {
        "implementing_agency": rec.implementing_agency, "agency_csr1": rec.agency_csr1,
        "via_agency": rec.via_agency, "is_ongoing": rec.is_ongoing, "amount": rec.amount,
        "project_count": rec.project_count, "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(conn, "funder_csr_spend", key, CSR_SPEND_UPDATABLE, proposed, document_id)


async def write_footprint(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
    location_id: int, document_id: int | None,
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "program_id": program_id,
           "fiscal_year": rec.fiscal_year, "location_id": location_id}
    proposed = {
        "name_as_printed": rec.name_as_printed, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(conn, "funder_footprints", key, FOOTPRINT_UPDATABLE, proposed, document_id)


async def write_funder_location(
    conn: Any, rec: Any, funder_id: int, *, location_id: int, document_id: int | None
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "location_id": location_id}
    proposed = {
        "role": rec.role, "note": rec.note, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(
        conn, "funder_locations", key, FUNDER_LOCATION_UPDATABLE, proposed, document_id
    )


async def write_partner(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "program_id": program_id,
           "fiscal_year": rec.fiscal_year, "partner_name": rec.partner_name}
    proposed = {
        "partner_canonical": rec.partner_canonical or rec.partner_name,
        "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(conn, "funder_partners", key, PARTNER_UPDATABLE, proposed, document_id)


async def write_program(
    conn: Any, rec: Any, funder_id: int, *, parent_id: int | None, document_id: int | None
) -> tuple[str, int, dict]:
    """Returns (status, program_id, changes) — the id is needed by every fact
    that names a programme."""
    key = {"funder_id": funder_id, "name": rec.name}
    proposed = {
        "description": rec.description, "status": rec.status, "start_date": rec.start_date,
        "end_date": rec.end_date, "parent_id": parent_id, "kind": rec.program_kind,
        "is_enabler": rec.is_enabler, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    status, changes = await _upsert(
        conn, "programs", key, PROGRAM_UPDATABLE, proposed, document_id
    )
    row = await (
        await conn.execute(
            "SELECT id FROM programs WHERE funder_id = %s AND name = %s", (funder_id, rec.name)
        )
    ).fetchone()
    return status, row["id"], changes


async def write_metric(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
    location_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "name": rec.name, "period": rec.period,
           "program_id": program_id}
    proposed = {
        "value": rec.value, "target": rec.target, "unit": rec.unit, "stage": rec.stage,
        "method": rec.method, "is_self_reported": rec.is_self_reported,
        "baseline": rec.baseline, "comparison_value": rec.comparison_value,
        "chain_key": rec.chain_key, "sequence": rec.sequence, "location_id": location_id,
        "notes": rec.notes, "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(conn, "metrics", key, METRIC_UPDATABLE, proposed, document_id)


async def write_contact(
    conn: Any, rec: Any, funder_id: int, *, document_id: int | None
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "name": rec.name, "role": rec.role}
    proposed = {
        "kind": rec.contact_kind, "email": rec.email,
        # A shared mailbox the funder published is public by definition; the
        # column defaults to false and nothing else here sets it.
        "is_public": True if rec.email else None,
        "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    return await _upsert(conn, "contacts", key, CONTACT_UPDATABLE, proposed, document_id)


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
    status, changes = await _upsert(conn, "rfps", key, RFP_UPDATABLE, proposed, document_id)
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


async def write_funder_tag(conn: Any, funder_id: int, tag_id: int, *, note: str | None) -> None:
    """A theme this funder actually spends on, so field-8 questions can be
    answered from one place instead of aggregated over spend rows.

    is_inferred is always true: the clause was chosen from the funder's own
    wording by a keyword table, and the row should say that rather than read
    as the funder's own classification.
    """
    await conn.execute(
        "INSERT INTO funder_tags (funder_id, tag_id, role, is_inferred, tagged_by, note) "
        "VALUES (%s, %s, 'primary', true, %s, %s) "
        "ON CONFLICT (funder_id, tag_id) DO NOTHING",
        (funder_id, tag_id, EXTRACTOR_TAGGER, note),
    )
