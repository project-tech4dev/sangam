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

from app.ingest.expectations import PROMOTABLE
from app.ingest.geography import resolve_location
from app.ingest.matcher import resolve_funder, resolve_org
from app.ingest.records import (
    ContactRecord,
    FunderCsrSpendRecord,
    FunderCsrYearRecord,
    FunderFootprintRecord,
    FunderLocationRecord,
    FunderPartnerRecord,
    FunderRecord,
    MetricRecord,
    OrgFinancialsRecord,
    OrgLocationRecord,
    OrgRecord,
    ProgramRecord,
    RfpRecord,
)
from app.ingest.research_records import FINDING_MODELS, SCHEMA_VERSION, to_inr
from app.ingest.taxonomy import resolve_csr_sector
from app.ingest.writer import (
    Owner,
    ensure_document,
    set_registered_location,
    write_contact,
    write_csr_spend,
    write_csr_year,
    write_footprint,
    write_funder,
    write_funder_location,
    write_funder_tag,
    write_metric,
    write_org,
    write_org_financials,
    write_org_location,
    write_partner,
    write_program,
    write_rfp,
)
from app.integrations import storage

logger = logging.getLogger(__name__)

# The matcher methods that mean "this is the same organisation". 'trigram'
# proposes and a person accepts; 'none' is a new entity.
MERGEABLE = ("identifier", "exact", "alias", "boilerplate")

# Documents first, so every other fact can cite the report it was read from.
# Programmes next, because every remaining concept can name one and a spend row
# whose program_id is null for want of ordering is a quietly weaker row.
WRITE_ORDER = (
    "csr_spend", "footprint", "stated_geography", "partner", "metric", "contact", "rfp",
)

# The org side's own order. Separate rather than appended: the funder path
# would otherwise try concepts whose findings it never has, and the shared
# concepts — programme, metric, contact, document — are the only overlap.
ORG_WRITE_ORDER = ("org_financials", "org_location", "metric", "contact")


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
    "rfp": RfpRecord,
    "org_identity": OrgRecord,
    "org_identifier": OrgRecord,
    "org_financials": OrgFinancialsRecord,
    "org_location": OrgLocationRecord,
}

# A finding field whose record field has a different name. `kind` collides
# with the records' own discriminator, hence the prefixes.
RENAMED: dict[tuple[str, str], str] = {
    ("program", "kind"): "program_kind",
    ("contact", "kind"): "contact_kind",
    ("identifier", "id_type"): "identifiers",
    ("identifier", "id_value"): "identifiers",
    ("org_identifier", "id_type"): "identifiers",
    ("org_identifier", "id_value"): "identifiers",
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


def org_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> OrgRecord | None:
    """One org record, the same shape as funder_from on the other kind.

    The website is deliberately absent: orgs has no column for one, and
    _hold_unstorable reports it rather than letting it disappear here.
    """
    identity = next((f for f in findings if f["concept"] == "org_identity"), None)
    identifiers = [f for f in findings if f["concept"] == "org_identifier"]
    anchor = identity or (identifiers[0] if identifiers else None)
    if anchor is None:
        return None
    try:
        return OrgRecord(
            name=(identity or {}).get("name") or row["canonical_name"] or row["entity_name"],
            org_kind=(identity or {}).get("org_kind") or "cso",
            legal_form=(identity or {}).get("legal_form"),
            registration_date=(identity or {}).get("registration_date"),
            identifiers={f["id_type"]: f["id_value"] for f in identifiers},
            as_of=None,
            **_provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("org record refused for %s: %s", row["slug"], exc)
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
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    report: dict[str, Any],
) -> dict[str, int]:
    """Returns source_url -> document id, so many facts can cite one report."""
    # funders and orgs both key their archive folder on the catalog slug,
    # which is assigned at write time and so is not known before now.
    table = "orgs" if owner.column == "org_id" else "funders"
    slug = (await (await conn.execute(
        f"SELECT slug FROM {table} WHERE id = %s", (owner.id,)
    )).fetchone())["slug"]

    by_url: dict[str, int] = {}
    for f in _validated(findings, "document"):
        shim = type("Doc", (), {
            "source_url": f.source_url, "title": f.title,
            "source_name": f.source_name or "research",
            "fetched_at": row["researched_at"], "as_of": f.as_of,
        })()
        # Whether the research run managed to archive this URL. Looked up
        # rather than assumed: a page read with read_page was never downloaded,
        # and claiming a storage_path for it would be a lie about provenance.
        # Storage being unreachable returns None here, never raises.
        key = await storage.archived_key(storage.SOURCE_ARCHIVE, f.source_url)
        digest = storage.hash_from_key(key) if key else None
        if key:
            key = await _shelve(key, slug, f.as_of, digest, prefix=table)
        document_id, status = await ensure_document(
            conn, shim, owner=owner, doc_type=f.doc_type,
            storage_path=storage.qualify(storage.SOURCE_ARCHIVE, key) if key else None,
            content_hash=digest,
        )
        by_url[f.source_url] = document_id
        _count(report, "documents", status)
    return by_url


async def _shelve(
    key: str, slug: str, as_of: str | None, digest: str | None, *, prefix: str = "funders"
) -> str:
    """Move a just-archived object to a name a person can read, now that the
    funder is known. Returns wherever the object actually ended up.

    Fetching cannot name the file: `fetch_document` runs during research, so it
    has only the URL and the bytes to key on. Promotion has the funder and the
    period, which is what makes `funders/<slug>/2023-annual-report.pdf`
    possible. The leftovers are informative — an object still under a hash
    folder is one we downloaded and no finding ever cited.
    """
    destination = storage.catalog_key(slug, as_of, storage.filename_from_key(key), prefix=prefix)
    if destination == key:
        return key
    # Same funder, same year, same published filename, different bytes. Rare,
    # and silently overwriting one with the other would lose a source.
    if await storage.stat(storage.SOURCE_ARCHIVE, destination) is not None:
        destination = storage.catalog_key(
            slug, as_of, storage.filename_from_key(key), suffix=(digest or "")[:8],
            prefix=prefix,
        )
    return destination if await storage.move(
        storage.SOURCE_ARCHIVE, key, destination
    ) else key


async def _write_programs(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    docs: dict[str, int], report: dict[str, Any],
) -> dict[str, int]:
    """Returns programme name -> id, so later concepts can resolve program_name."""
    # A theme has to exist before a phase can point at it, so shallowest first.
    depth = {"theme": 0, "programme": 1, "phase": 2, "project": 3}
    ids: dict[str, int] = {}
    for f in sorted(_validated(findings, "program"), key=lambda f: depth.get(f.kind, 9)):
        try:
            rec = ProgramRecord(
                entity_name=row["canonical_name"] or row["entity_name"], name=f.name,
                program_kind=f.kind, description=f.description, status=f.status,
                start_date=f.start_date, end_date=f.end_date, is_enabler=f.is_enabler,
                as_of=None, **_provenance(f, row["researched_at"]),
            )
        except ValidationError as exc:
            report["held"].append(f"programme {f.name!r}: {exc.errors()[0]['msg']}")
            continue
        status, program_id, _ = await write_program(
            conn, rec, owner, parent_id=ids.get(f.parent_name or ""),
            document_id=docs.get(f.source_url),
        )
        ids[f.name] = program_id
        _count(report, "programs", status)
    return ids


def _row_identity(
    concept: str, f: Any, program_id: int | None, state_id: int | None,
    district_id: int | None, sector_id: int | None,
) -> tuple:
    """The row a finding will occupy, after every name has been resolved to an id.

    Mirrors each writer's natural key. It is deliberately computed here rather
    than inside the writer: the collision is between two findings in one
    payload, which the writer never sees together.
    """
    year = getattr(f, "fiscal_year", None)
    if concept == "csr_spend":
        return (concept, year, program_id, sector_id, state_id, district_id,
                f.designation, f.project_name)
    if concept == "footprint":
        return (concept, program_id, year, district_id or state_id)
    if concept == "stated_geography":
        return (concept, district_id or state_id)
    if concept == "partner":
        return (concept, program_id, year, f.partner_name)
    if concept == "metric":
        return (concept, f.name, f.period, program_id)
    if concept == "contact":
        return (concept, f.name, f.role)
    if concept == "rfp":
        return (concept, f.title, f.deadline)
    if concept == "org_location":
        return (concept, district_id or state_id)
    if concept == "org_financials":
        return (concept, year)
    return (concept, id(f))


def _describe(concept: str, f: Any) -> str:
    for attr in ("project_name", "partner_name", "title", "name", "sector", "state"):
        value = getattr(f, attr, None)
        if value:
            return f"{attr}={value!r}"
    return getattr(f, "fiscal_year", None) or "no distinguishing field"


async def _write_facts(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    programs: dict[str, int], docs: dict[str, int], report: dict[str, Any],
    *, order: tuple[str, ...] = WRITE_ORDER,
) -> None:
    """Every remaining concept, in dependency order.

    `order` is what keeps the two kinds apart: the funder-only branches below
    read funder_id, and an org run never reaches them because ORG_WRITE_ORDER
    names none of their concepts.
    """
    funder_id = owner.id
    name = row["canonical_name"] or row["entity_name"]
    fetched = row["researched_at"]
    seen: set[tuple] = set()
    themes: dict[int, str] = {}

    for concept in order:
        for f in _validated(findings, concept):
            program_id = programs.get(getattr(f, "program_name", None) or "")
            document_id = docs.get(f.source_url)
            state_id, district_id = await _place(conn, f, report)
            sector_id = await resolve_csr_sector(conn, getattr(f, "sector", None))
            if sector_id is not None:
                themes.setdefault(sector_id, getattr(f, "sector", "") or "")
            prov = _provenance(f, fetched)
            # metric and contact sit on tables with both foreign keys, so
            # they name the entity; the rest are funder-only records.
            base = {"funder_name": name, **prov}
            shared = {"entity_name": name, **prov}

            # Two findings can be distinct and still resolve to one row:
            # "Healthcare" and "Sanitation" are both Schedule VII clause (i),
            # and two programme names neither of which resolved are both a
            # NULL program_id. Writing both made each promote overwrite the
            # last — six rows churned on every run, forever, with no duplicate
            # to show for it. Two sources that disagree is a finding, not an
            # edit, so the second is reported and left alone.
            identity = _row_identity(concept, f, program_id, state_id, district_id, sector_id)
            if identity in seen:
                report["held"].append(
                    f"{concept}: two findings resolve to the same row "
                    f"({_describe(concept, f)}). The first was written; the second is "
                    f"reported rather than overwriting it."
                )
                continue
            seen.add(identity)
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
                        district_id=district_id,
                        csr_sector_id=sector_id, document_id=document_id,
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
                        sequence=f.sequence, notes=f.notes, as_of=f.period, **shared,
                    )
                    status, _ = await write_metric(
                        conn, rec, owner, program_id=program_id,
                        location_id=district_id or state_id, document_id=document_id,
                    )
                    _count(report, "metrics", status)

                elif concept == "rfp":
                    rec = RfpRecord(
                        title=f.title, status=f.status, url=f.url, deadline=f.deadline,
                        amount_min=f.amount_min.inr if f.amount_min else None,
                        amount_max=f.amount_max.inr if f.amount_max else None,
                        eligibility=f.eligibility, state=f.state, district=f.district,
                        sector=f.sector, as_of=None, **base,
                    )
                    status, _, _ = await write_rfp(
                        conn, rec, funder_id,
                        location_id=district_id or state_id,
                        tag_id=sector_id, document_id=document_id,
                    )
                    _count(report, "rfps", status)

                elif concept == "org_financials":
                    rec = OrgFinancialsRecord(
                        fiscal_year=f.fiscal_year,
                        total_income=f.total_income.inr if f.total_income else None,
                        program_spend=f.program_spend.inr if f.program_spend else None,
                        non_program_spend=(
                            f.non_program_spend.inr if f.non_program_spend else None
                        ),
                        foreign_contribution=(
                            f.foreign_contribution.inr if f.foreign_contribution else None
                        ),
                        is_audited=f.is_audited, notes=f.notes, as_of=f.fiscal_year, **shared,
                    )
                    status, _ = await write_org_financials(
                        conn, rec, owner.id, document_id
                    )
                    _count(report, "org_financials", status)

                elif concept == "org_location":
                    location_id = district_id or state_id
                    if location_id is None:
                        continue
                    rec = OrgLocationRecord(
                        state=f.state, district=f.district, role=f.role, note=f.note,
                        as_of=None, **shared,
                    )
                    status, _ = await write_org_location(
                        conn, rec, owner.id, location_id=location_id, document_id=document_id
                    )
                    _count(report, "org_locations", status)
                    # A registered address is this concept with role='registered',
                    # not a second field on org_identity — so the column that
                    # names it is set here, where the place is already resolved.
                    if f.role == "registered":
                        await set_registered_location(conn, owner.id, location_id)

                elif concept == "contact":
                    rec = ContactRecord(
                        name=f.name, contact_kind=f.kind, role=f.role, email=f.email,
                        is_role_mailbox=f.is_role_mailbox, notes=f.notes, as_of=None, **shared,
                    )
                    status, _ = await write_contact(
                        conn, rec, owner, document_id=document_id
                    )
                    _count(report, "contacts", status)

            except ValidationError as exc:
                report["held"].append(f"{concept}: {exc.errors()[0]['msg']}")

    # Every Schedule VII clause this funder's spending touched, recorded once
    # against the funder with the wording that placed it there. org_tags is
    # not a concept, and nothing on the org side resolves a sector anyway.
    for tag_id, wording in themes.items() if owner.column == "funder_id" else ():
        await write_funder_tag(
            conn, funder_id, tag_id, note=f"from research: {wording}" if wording else None
        )


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
        return match.entity_id
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


async def _link_research(
    conn: Any, row: dict[str, Any], *, org_id: int | None = None, funder_id: int | None = None
) -> None:
    """What this research row became. Both columns, always: the pair existed
    unwritten and unread since 0011, and filling one of them would leave the
    other looking deliberately empty."""
    await conn.execute(
        "UPDATE entity_research SET resolved_org_id = %s, resolved_funder_id = %s WHERE id = %s",
        (org_id, funder_id, row["id"]),
    )


def _hold_unstorable(row: dict[str, Any], findings: list[dict[str, Any]], report) -> None:
    """Two org facts that are researched, correct, and have nowhere to go.

    Reported rather than dropped, because "we never asked" and "there is no
    column" are different answers and only one of them is ours to fix.
    """
    if row.get("website"):
        report["held"].append(
            f"website {row['website']!r}: orgs has no column for one and org_identifiers has "
            f"no 'domain' type, so it stays on the research row."
        )
    for f in findings:
        if f["concept"] == "org_identifier" and f.get("notes"):
            report["held"].append(
                f"{f['id_type']} note {f['notes']!r}: the identifier map carries a type and a "
                f"value, so the note stays on the research row."
            )


async def _promote_funder(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any]
) -> None:
    record = funder_from(row, findings)
    if record is None:
        report["reasons"].append("no identity or identifier finding to build a funder from")
        return

    match = await resolve_funder(conn, record.name, record.identifiers)
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["reasons"].append(
            f"{record.name!r} resembles {names} without matching. Not merged — a person decides."
        )
        return
    parent_id = await _parent(conn, record, report)
    status, funder_id, _ = await write_funder(conn, record, match, parent_id=parent_id)
    report["entity"] = {
        "kind": "funder", "status": status, "id": funder_id, "name": record.name
    }

    owner = Owner.funder(funder_id)
    docs = await _write_documents(conn, row, findings, owner, report)
    for year_record in csr_years_from(row, findings):
        state, _ = await write_csr_year(
            conn, year_record, funder_id, docs.get(year_record.source_url)
        )
        report["csr_years"].append({"fiscal_year": year_record.fiscal_year, "status": state})
    programs = await _write_programs(conn, row, findings, owner, docs, report)
    await _write_facts(conn, row, findings, owner, programs, docs, report)
    await _link_research(conn, row, funder_id=funder_id)


async def _promote_org(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any]
) -> None:
    """The NGO path. Same shape as the funder one bar two differences: there is
    no parent link to resolve, and write_org fills blanks instead of winning."""
    record = org_from(row, findings)
    if record is None:
        report["reasons"].append(
            "no org_identity or org_identifier finding to build an organisation from"
        )
        return

    match = await resolve_org(conn, record.name, record.identifiers)
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["reasons"].append(
            f"{record.name!r} resembles {names} without matching. Not merged — a person decides."
        )
        return
    status, org_id, _, conflicts = await write_org(conn, record, match)
    report["entity"] = {"kind": "org", "status": status, "id": org_id, "name": record.name}
    report["held"].extend(conflicts)
    _hold_unstorable(row, findings, report)

    owner = Owner.org(org_id)
    docs = await _write_documents(conn, row, findings, owner, report)
    programs = await _write_programs(conn, row, findings, owner, docs, report)
    await _write_facts(
        conn, row, findings, owner, programs, docs, report, order=ORG_WRITE_ORDER
    )
    await _link_research(conn, row, org_id=org_id)


async def promote(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Write what can be written from one research row. Returns a report."""
    findings = row["findings"] if isinstance(row["findings"], list) else []
    report: dict[str, Any] = {
        "slug": row["slug"], "entity": None, "csr_years": [],
        "written": {}, "held": [], "skipped": {}, "reasons": [],
    }
    for concept in sorted({f["concept"] for f in findings}):
        if concept not in PROMOTABLE:
            report["skipped"][concept] = len([f for f in findings if f["concept"] == concept])

    # Before the kind branch, not after it. An org row researched under the old
    # shape used to be turned away for having no writer, which is a reason that
    # has stopped existing; "re-run the research" is the one that says what to do.
    if findings and row.get("schema_version", 1) < SCHEMA_VERSION:
        report["reasons"].append(
            f"researched under finding shape v{row.get('schema_version', 1)}, which has no typed "
            f"fields to map. Re-run the research for {row['slug']} and promote that."
        )
        return report

    # An NGO is not a funder, and the two kinds reach different tables through
    # different resolvers. Nothing below this line is shared but the report.
    if row.get("entity_kind") == "org":
        await _promote_org(conn, row, findings, report)
    else:
        await _promote_funder(conn, row, findings, report)
    # Ten findings citing the same unresolvable state is one problem, not ten.
    report["held"] = list(dict.fromkeys(report["held"]))
    return report


def now() -> datetime:
    return datetime.now(UTC)
