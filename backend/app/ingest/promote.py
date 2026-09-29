"""Move research findings into the catalog, where a writer exists for them.

Research and catalog are different things. A finding is what a source said,
with the sentence that says it; a catalog row is a fact the product answers
questions from. This is the deliberate step between them, and it only moves
what there is somewhere to move — the rest is reported, not silently dropped.

Findings arrive typed (app/ingest/research_records.py), so this file maps
fields to columns. It does not parse. The version before it read free text with
regular expressions and refused a real figure because it could not tell crore
from rupees, which was the good half of that failure mode.
"""

from __future__ import annotations

import collections
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.ingest.geography import resolve_location
from app.ingest.matcher import resolve_funder
from app.ingest.records import (
    ContactRecord,
    FunderCsrSpendRecord,
    FunderCsrYearRecord,
    FunderFootprintRecord,
    FunderLocationRecord,
    FunderPartnerRecord,
    FunderRecord,
    MetricRecord,
    ProgramRecord,
)
from app.ingest.research_records import FINDING_MODELS, SCHEMA_VERSION, to_inr
from app.ingest.writer import (
    ensure_document,
    write_contact,
    write_csr_spend,
    write_csr_year,
    write_footprint,
    write_funder,
    write_funder_location,
    write_metric,
    write_partner,
    write_program,
)

logger = logging.getLogger(__name__)

# Eleven of the twelve concepts. 'grant' is the exception: grants.org_id is NOT
# NULL and orgs has no writer, so a funded organisation we do not hold cannot
# become a grant row. It belongs in funder_partners. See docs/INGEST.md.
# The matcher methods that mean "this is the same organisation". 'trigram'
# proposes and a person accepts; 'none' is a new entity.
MERGEABLE = ("identifier", "exact", "alias", "boilerplate")

PROMOTABLE = (
    "identity", "identifier", "csr_year", "document", "program", "csr_spend",
    "footprint", "stated_geography", "partner", "metric", "contact",
)

# Documents first, so every other fact can cite the report it was read from.
# Programmes next, because every remaining concept can name one and a spend row
# whose program_id is null for want of ordering is a quietly weaker row.
WRITE_ORDER = ("csr_spend", "footprint", "stated_geography", "partner", "metric", "contact")


# The provenance convention in CLAUDE.md asks for content_hash and
# extractor_version on every extracted row. Nothing in the ingest path wrote
# either. The hash is over the sentence and the URL, so re-reading the same
# claim from the same page is recognisably the same fact.
EXTRACTOR_VERSION = f"research/v{SCHEMA_VERSION}"


# Which record type carries each concept into the writer. A finding field with
# no matching record field is a field that gets researched and thrown away —
# seven of them were, until test_every_finding_field_reaches_a_record caught it.
CONCEPT_RECORDS: dict[str, type] = {
    "identity": FunderRecord,
    "identifier": FunderRecord,
    "csr_year": FunderCsrYearRecord,
    "csr_spend": FunderCsrSpendRecord,
    "footprint": FunderFootprintRecord,
    "stated_geography": FunderLocationRecord,
    "partner": FunderPartnerRecord,
    "program": ProgramRecord,
    "metric": MetricRecord,
    "contact": ContactRecord,
}

# A finding field whose record field has a different name. `kind` collides
# with the records' own discriminator, hence the prefixes.
RENAMED: dict[tuple[str, str], str] = {
    ("program", "kind"): "program_kind",
    ("contact", "kind"): "contact_kind",
    ("identifier", "id_type"): "identifiers",
    ("identifier", "id_value"): "identifiers",
}

# Researched deliberately and deliberately not stored as its own column. Each
# entry is a decision; an undocumented gap is a bug.
NOT_WRITTEN: dict[str, dict[str, str]] = {
    "csr_spend": {
        "sector": "kept in funder_csr_spend.notes: tags.kind allows 'csr_sector' but no "
                  "Schedule VII taxonomy is seeded to normalise against",
    },
    "document": {
        "title": "written by ensure_document, which takes a shim rather than a record",
        "doc_type": "written by ensure_document",
        "as_of": "written by ensure_document",
    },
    # The whole concept. grants.org_id is NOT NULL and there is no writer for
    # orgs, so a funded organisation the catalog does not hold cannot become a
    # grant row at all. Such a relationship goes to funder_partners, whose
    # org_id is nullable — and which is the more honest claim anyway, since a
    # named partner is not proof that money changed hands.
    "grant": dict.fromkeys(
        (
            "recipient_name", "title", "status", "amount", "currency",
            "start_date", "end_date", "program_name", "notes",
        ),
        "grants.org_id is NOT NULL and orgs has no writer; recorded as a partner instead",
    ),
}


def _provenance(finding: dict[str, Any] | Any, fetched: datetime) -> dict[str, Any]:
    get = finding.get if isinstance(finding, dict) else lambda k: getattr(finding, k, None)
    url = get("source_url") or ""
    evidence = get("evidence") or ""
    return {
        "source_url": url,
        "source_name": get("source_name") or "research",
        "fetched_at": fetched,
        "content_hash": hashlib.sha256(f"{url}\n{evidence}".encode()).hexdigest(),
        "extractor_version": EXTRACTOR_VERSION,
    }


def _validated(findings: list[dict[str, Any]], concept: str) -> list[Any]:
    """Findings come back out of jsonb as plain dicts. Re-validating each one
    through its own model is what lets the writers map instead of parse, and
    catches a row stored before a field became required."""
    out = []
    for f in findings:
        if f.get("concept") != concept:
            continue
        try:
            out.append(FINDING_MODELS[concept].model_validate(f))
        except ValidationError as exc:
            logger.info("finding refused (%s): %s", concept, exc.errors()[0].get("msg"))
    return out


def _count(report: dict[str, Any], table: str, status: str) -> None:
    if status in ("added", "updated"):
        report["written"].setdefault(table, collections.Counter())[status] += 1


def funder_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> FunderRecord | None:
    """One funder record, from the identity finding and any identifiers."""
    identity = next((f for f in findings if f["concept"] == "identity"), None)
    identifiers = [f for f in findings if f["concept"] == "identifier"]
    anchor = identity or (identifiers[0] if identifiers else None)
    if anchor is None:
        return None
    try:
        return FunderRecord(
            name=(identity or {}).get("name") or row["canonical_name"] or row["entity_name"],
            funder_type=(identity or {}).get("funder_type"),
            website=(identity or {}).get("website") or row.get("website"),
            section_135_bound=(identity or {}).get("section_135_bound"),
            parent_name=(identity or {}).get("parent_name"),
            identifiers={f["id_type"]: f["id_value"] for f in identifiers},
            as_of=None,
            **_provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("funder record refused for %s: %s", row["slug"], exc)
        return None


def csr_years_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> list[FunderCsrYearRecord]:
    """One record per fiscal year. Each finding already names its own columns."""
    name = row["canonical_name"] or row["entity_name"]
    out = []
    for f in findings:
        if f["concept"] != "csr_year":
            continue
        try:
            out.append(
                FunderCsrYearRecord(
                    funder_name=name,
                    fiscal_year=f["fiscal_year"],
                    prescribed_csr=to_inr(f.get("prescribed_csr")),
                    total_spent=to_inr(f.get("total_spent")),
                    average_net_profit=to_inr(f.get("average_net_profit")),
                    unspent_transferred=to_inr(f.get("unspent_transferred")),
                    spent_on_projects=to_inr(f.get("spent_on_projects")),
                    admin_overheads=to_inr(f.get("admin_overheads")),
                    impact_assessment_cost=to_inr(f.get("impact_assessment_cost")),
                    excess_spent=to_inr(f.get("excess_spent")),
                    impact_assessment_done=f.get("impact_assessment_done"),
                    section_135_applicable=f.get("section_135_applicable"),
                    notes=f.get("notes") or f"Promoted from research: {f.get('evidence', '')[:200]}",
                    as_of=f["fiscal_year"],
                    **_provenance(f, row["researched_at"]),
                )
            )
        except ValueError as exc:
            logger.info("csr year refused for %s %s: %s", row["slug"], f.get("fiscal_year"), exc)
    return out


async def _place(conn: Any, f: Any, report: dict[str, Any]) -> tuple[int | None, int | None]:
    """(state_id, district_id). A place that will not resolve is reported, not
    guessed at — funder_footprints.location_id is NOT NULL, so the alternative
    to naming the problem is a missing row nobody hears about."""
    state = getattr(f, "state", None)
    if not state:
        return None, None
    state_id, reason = await resolve_location(conn, state)
    if reason:
        report["held"].append(reason)
        return None, None
    district = getattr(f, "district", None)
    if not district:
        return state_id, None
    district_id, reason = await resolve_location(conn, state, district)
    if reason:
        report["held"].append(reason)
    return state_id, district_id


async def _write_documents(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], funder_id: int,
    report: dict[str, Any],
) -> dict[str, int]:
    """Returns source_url -> document id, so many facts can cite one report."""
    by_url: dict[str, int] = {}
    for f in _validated(findings, "document"):
        shim = type("Doc", (), {
            "source_url": f.source_url, "title": f.title,
            "source_name": f.source_name or "research",
            "fetched_at": row["researched_at"], "as_of": f.as_of,
        })()
        # ensure_document returns an id either way, so ask first: reporting
        # "1 added" on every re-run would overstate what the run did.
        seen = await (
            await conn.execute("SELECT 1 FROM documents WHERE source_url = %s", (f.source_url,))
        ).fetchone()
        by_url[f.source_url] = await ensure_document(
            conn, shim, funder_id=funder_id, doc_type=f.doc_type
        )
        _count(report, "documents", "matched" if seen else "added")
    return by_url


async def _write_programs(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], funder_id: int,
    docs: dict[str, int], report: dict[str, Any],
) -> dict[str, int]:
    """Returns programme name -> id, so later concepts can resolve program_name."""
    # A theme has to exist before a phase can point at it, so shallowest first.
    depth = {"theme": 0, "programme": 1, "phase": 2, "project": 3}
    ids: dict[str, int] = {}
    for f in sorted(_validated(findings, "program"), key=lambda f: depth.get(f.kind, 9)):
        try:
            rec = ProgramRecord(
                funder_name=row["canonical_name"] or row["entity_name"], name=f.name,
                program_kind=f.kind, description=f.description, status=f.status,
                start_date=f.start_date, end_date=f.end_date, is_enabler=f.is_enabler,
                as_of=None, **_provenance(f, row["researched_at"]),
            )
        except ValidationError as exc:
            report["held"].append(f"programme {f.name!r}: {exc.errors()[0]['msg']}")
            continue
        status, program_id, _ = await write_program(
            conn, rec, funder_id, parent_id=ids.get(f.parent_name or ""),
            document_id=docs.get(f.source_url),
        )
        ids[f.name] = program_id
        _count(report, "programs", status)
    return ids


async def _write_facts(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], funder_id: int,
    programs: dict[str, int], docs: dict[str, int], report: dict[str, Any],
) -> None:
    """Every remaining concept, in dependency order."""
    name = row["canonical_name"] or row["entity_name"]
    fetched = row["researched_at"]

    for concept in WRITE_ORDER:
        for f in _validated(findings, concept):
            program_id = programs.get(getattr(f, "program_name", None) or "")
            document_id = docs.get(f.source_url)
            state_id, district_id = await _place(conn, f, report)
            base = {"funder_name": name, **_provenance(f, fetched)}
            try:
                if concept == "csr_spend":
                    rec = FunderCsrSpendRecord(
                        fiscal_year=f.fiscal_year, amount=f.amount.inr,
                        project_name=f.project_name, project_count=f.project_count,
                        designation=f.designation, implementing_agency=f.implementing_agency,
                        agency_csr1=f.agency_csr1, via_agency=f.via_agency,
                        is_ongoing=f.is_ongoing, as_of=f.fiscal_year,
                        notes=_with_sector(f), **base,
                    )
                    status, _ = await write_csr_spend(
                        conn, rec, funder_id, program_id=program_id, state_id=state_id,
                        district_id=district_id, document_id=document_id,
                    )
                    _count(report, "funder_csr_spend", status)

                elif concept == "footprint":
                    location_id = district_id or state_id
                    if location_id is None:
                        report["held"].append(
                            f"footprint {f.state!r}: no place to attach it to, and "
                            f"funder_footprints requires one"
                        )
                        continue
                    rec = FunderFootprintRecord(
                        fiscal_year=f.fiscal_year, state=f.state, district=f.district,
                        name_as_printed=f.name_as_printed or f.district or f.state,
                        notes=f.notes, as_of=f.fiscal_year, **base,
                    )
                    status, _ = await write_footprint(
                        conn, rec, funder_id, program_id=program_id,
                        location_id=location_id, document_id=document_id,
                    )
                    _count(report, "funder_footprints", status)

                elif concept == "stated_geography":
                    location_id = district_id or state_id
                    if location_id is None:
                        continue
                    rec = FunderLocationRecord(
                        state=f.state, district=f.district, role=f.role, note=f.note,
                        as_of=None, **base,
                    )
                    status, _ = await write_funder_location(
                        conn, rec, funder_id, location_id=location_id, document_id=document_id
                    )
                    _count(report, "funder_locations", status)

                elif concept == "partner":
                    rec = FunderPartnerRecord(
                        fiscal_year=f.fiscal_year, partner_name=f.partner_name,
                        partner_canonical=f.partner_canonical, partner_kind=f.partner_kind,
                        partner_csr1=f.partner_csr1, notes=f.notes, as_of=f.fiscal_year, **base,
                    )
                    status, _ = await write_partner(
                        conn, rec, funder_id, program_id=program_id, document_id=document_id
                    )
                    _count(report, "funder_partners", status)

                elif concept == "metric":
                    rec = MetricRecord(
                        name=f.name, value=f.value, target=f.target, unit=f.unit,
                        period=f.period, stage=f.stage, method=f.method,
                        is_self_reported=f.is_self_reported, baseline=f.baseline,
                        comparison_value=f.comparison_value, chain_key=f.chain_key,
                        sequence=f.sequence, notes=f.notes, as_of=f.period, **base,
                    )
                    status, _ = await write_metric(
                        conn, rec, funder_id, program_id=program_id,
                        location_id=district_id or state_id, document_id=document_id,
                    )
                    _count(report, "metrics", status)

                elif concept == "contact":
                    rec = ContactRecord(
                        name=f.name, contact_kind=f.kind, role=f.role, notes=f.notes,
                        as_of=None, **base,
                    )
                    status, _ = await write_contact(
                        conn, rec, funder_id, document_id=document_id
                    )
                    _count(report, "contacts", status)

            except ValidationError as exc:
                report["held"].append(f"{concept}: {exc.errors()[0]['msg']}")


def _with_sector(f: Any) -> str | None:
    """The funder's own words for a theme. tags.kind allows 'csr_sector' but
    nothing seeds that taxonomy, so normalising here would invent the mapping
    — "Building Human Capital" is not Education until someone decides it is."""
    bits = [b for b in (f.sector, f.notes) if b]
    return " · ".join(bits) or None


async def _parent(conn: Any, record: FunderRecord, report: dict[str, Any]) -> int | None:
    """The parent company's funder id, when it is already in the catalog.

    A parent that does not resolve is reported, never created. "Never merge a
    company with its foundation" cuts both ways: inventing Axis Bank Limited
    because Axis Bank Foundation mentioned it puts a row in the catalog that no
    source was read for.
    """
    if not record.parent_name:
        return None
    match = await resolve_funder(conn, record.parent_name)
    # Explicit about the methods rather than relying on Match.resolved: a
    # trigram hit happens to carry funder_id=None, so this was safe by accident
    # of the dataclass. A near-miss parent — ITC Limited against ITC Infotech —
    # is precisely the link that must not be stored quietly.
    if match.method in MERGEABLE:
        return match.funder_id
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["held"].append(
            f"parent {record.parent_name!r} of {record.name!r} resembles {names} without "
            f"matching. Not linked — a person decides which, if either, it is."
        )
        return None
    report["held"].append(
        f"parent {record.parent_name!r} of {record.name!r} is not in the catalog, so the link "
        f"is not stored. Research the parent and promote it first."
    )
    return None


async def promote(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Write what can be written from one research row. Returns a report."""
    findings = row["findings"] if isinstance(row["findings"], list) else []
    report: dict[str, Any] = {
        "slug": row["slug"], "funder": None, "csr_years": [],
        "written": {}, "held": [], "skipped": {}, "reasons": [],
    }
    for concept in sorted({f["concept"] for f in findings}):
        if concept not in PROMOTABLE:
            report["skipped"][concept] = len([f for f in findings if f["concept"] == concept])

    # An NGO is not a funder. Without this the first org researched becomes a
    # funders row, which is worse than not promoting it at all: it is a wrong
    # answer wearing a catalog citation.
    if row.get("entity_kind") == "org":
        report["reasons"].append(
            "researched as an organisation, not a funder. orgs has no writer yet "
            "(no OrgRecord, no resolve_org, no write_org), so this stays research. "
            "See docs/INGEST.md."
        )
        return report

    # Flat label/value findings cannot be mapped to columns without the
    # guessing this file was rewritten to remove. Re-research, do not migrate.
    if findings and row.get("schema_version", 1) < SCHEMA_VERSION:
        report["reasons"].append(
            f"researched under finding shape v{row.get('schema_version', 1)}, which has no typed "
            f"fields to map. Re-run the research for {row['slug']} and promote that."
        )
        return report

    record = funder_from(row, findings)
    if record is None:
        report["reasons"].append("no identity or identifier finding to build a funder from")
        return report

    match = await resolve_funder(conn, record.name, record.identifiers)
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["reasons"].append(
            f"{record.name!r} resembles {names} without matching. Not merged — a person decides."
        )
        return report
    parent_id = await _parent(conn, record, report)
    status, funder_id, _ = await write_funder(conn, record, match, parent_id=parent_id)
    report["funder"] = {"status": status, "id": funder_id, "name": record.name}

    docs = await _write_documents(conn, row, findings, funder_id, report)
    for year_record in csr_years_from(row, findings):
        state, _ = await write_csr_year(
            conn, year_record, funder_id, docs.get(year_record.source_url)
        )
        report["csr_years"].append({"fiscal_year": year_record.fiscal_year, "status": state})
    programs = await _write_programs(conn, row, findings, funder_id, docs, report)
    await _write_facts(conn, row, findings, funder_id, programs, docs, report)
    # Ten findings citing the same unresolvable state is one problem, not ten.
    report["held"] = list(dict.fromkeys(report["held"]))
    return report


def now() -> datetime:
    return datetime.now(UTC)
