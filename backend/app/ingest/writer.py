"""The only code that writes imported data. Fixed SQL, never model-authored."""

from __future__ import annotations

import re
from typing import Any

from app.ingest.matcher import Match
from app.ingest.records import FunderCsrYearRecord, FunderRecord, NewsMentionRecord

# Columns a re-import may overwrite on an existing funder. Everything else on the
# row was either hand-vetted or set by a different source, so an importer leaves it.
FUNDER_UPDATABLE = ("funder_type", "website", "source_url", "source_name", "fetched_at", "as_of")
CSR_YEAR_UPDATABLE = (
    "prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred",
    "section_135_applicable", "notes", "source_url", "source_name", "fetched_at", "as_of",
)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def _diff(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Columns whose value actually changes; a proposed NULL never erases a value."""
    out: dict[str, dict[str, Any]] = {}
    for col, new in proposed.items():
        if new is None:
            continue
        old = existing.get(col)
        if isinstance(old, str) and isinstance(new, str):
            same = old.strip() == new.strip()
        elif old is not None and isinstance(new, int | float) and not isinstance(new, bool):
            same = abs(float(old) - float(new)) < 1e-9
        else:
            same = old == new
        if not same:
            out[col] = {"old": _plain(old), "new": _plain(new)}
    return out


def _plain(v: Any) -> Any:
    return v if v is None or isinstance(v, str | int | float | bool) else str(v)


async def ensure_document(conn: Any, rec: Any, *, funder_id: int | None, doc_type: str) -> int:
    """One documents row per source URL, so many facts can cite one report."""
    row = await (
        await conn.execute("SELECT id FROM documents WHERE source_url = %s", (rec.source_url,))
    ).fetchone()
    if row:
        return row["id"]
    row = await (
        await conn.execute(
            "INSERT INTO documents (funder_id, title, doc_type, source_url, source_name, "
            "fetched_at, as_of, is_public, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, true, 'read') RETURNING id",
            (funder_id, getattr(rec, "title", None), doc_type, rec.source_url,
             rec.source_name, rec.fetched_at, rec.as_of),
        )
    ).fetchone()
    return row["id"]


async def write_funder(conn: Any, rec: FunderRecord, match: Match) -> tuple[str, int, dict]:
    """Returns (status, funder_id, changes). Status is added | updated | matched."""
    proposed = {
        "funder_type": rec.funder_type, "website": rec.website, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
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
            "INSERT INTO funders (slug, name, funder_type, website, registry_status, "
            "source_url, source_name, fetched_at, as_of) "
            "VALUES (%s, %s, %s, %s, 'placeholder', %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.funder_type, rec.website, rec.source_url,
             rec.source_name, rec.fetched_at, rec.as_of),
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
    import json

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
                     "is_enabler", "source_url", "source_name", "fetched_at", "as_of")
METRIC_KEY = ("funder_id", "name", "period", "program_id")
METRIC_UPDATABLE = ("value", "target", "unit", "stage", "method", "is_self_reported",
                    "baseline", "comparison_value", "chain_key", "sequence", "location_id",
                    "notes", "source_url", "source_name", "fetched_at", "as_of")
CONTACT_KEY = ("funder_id", "name", "role")
CONTACT_UPDATABLE = ("kind", "notes", "source_url", "source_name", "fetched_at", "as_of")


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
    state_id: int | None, district_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = {
        "funder_id": funder_id, "fiscal_year": rec.fiscal_year, "program_id": program_id,
        "csr_sector_id": None, "state_location_id": state_id,
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
        "kind": rec.contact_kind, "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(conn, "contacts", key, CONTACT_UPDATABLE, proposed, document_id)
