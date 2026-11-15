"""The fact rows promote writes, one concept at a time in WRITE_ORDER."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.ingest.catalog.matcher import resolve_funder, resolve_org
from app.ingest.catalog.promote_documents import Programmes
from app.ingest.catalog.promote_records import (
    MERGEABLE,
    WRITE_ORDER,
    Mark,
    count_write,
    provenance,
    untiered,
    validated,
)
from app.ingest.catalog.rows import (
    ContactRecord,
    EligibilityGuidelineRecord,
    FunderCsrSpendRecord,
    FunderFootprintRecord,
    FunderLocationRecord,
    FunderPartnerRecord,
    FunderProgrammeSpendRecord,
    MetricRecord,
    OrgFinancialsRecord,
    OrgIdentifierRecord,
    OrgLocationRecord,
    RfpRecord,
)
from app.ingest.catalog.writer import Conflict, Owner
from app.ingest.catalog.writer_funder import (
    write_contact,
    write_csr_spend,
    write_eligibility_document,
    write_footprint,
    write_funder_location,
    write_funder_tag,
    write_metric,
    write_partner,
    write_programme_spend,
    write_rfp,
)
from app.ingest.catalog.writer_org import (
    set_registered_location,
    write_org_financials,
    write_org_identifier,
    write_org_location,
)
from app.ingest.geography import resolve_location
from app.ingest.research.expectations import activity_kind
from app.ingest.taxonomy import resolve_classification, resolve_csr_sector


async def _partner_org(conn: Any, name: str) -> tuple[int, str] | None:
    """(id, orgs.name) of the organisation a partner line names, only on a match the matcher would merge."""
    match = await resolve_org(conn, name)
    if match.method not in MERGEABLE:
        return None
    found = await (await conn.execute("SELECT name FROM orgs WHERE id = %s", (match.entity_id,))).fetchone()
    return match.entity_id, found["name"]


async def _org_line(conn: Any, funder_id: int, org_id: int, fiscal_year: str) -> list[dict[str, Any]]:
    """A funder's partner lines for one organisation in one year, whatever programme or title they carry."""
    return await (await conn.execute(
        "SELECT id, program_id, project_name, partner_name FROM funder_activity WHERE funder_id = %s "
        "AND kind = 'partner' AND partner_org_id = %s AND fiscal_year = %s ORDER BY id",
        (funder_id, org_id, fiscal_year),
    )).fetchall()


async def _place(conn: Any, f: Any, report: dict[str, Any]) -> tuple[int | None, int | None]:
    """(state_id, district_id). A place that will not resolve is reported, not
    guessed at — a footprint line needs a place, so the alternative
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
        # A near match is written and said; anything less certain is held for a person.
        report["held" if district_id is None else "reasons"].append(reason)
    return state_id, district_id


def _activity_identity(
    kind: str, year: str | None, program_id: int | None, sector_id: int | None,
    state_id: int | None, location_id: int | None, designation: str | None,
    project_name: str | None, partner_name: str | None,
) -> tuple:
    """writer_funder.FUNDER_ACTIVITY_KEY without funder_id, in its order."""
    return (kind, year, program_id, sector_id, state_id, location_id, designation, project_name,
            partner_name)


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
        return _activity_identity(activity_kind(concept), year, program_id, sector_id, state_id,
                                  district_id, f.designation, f.project_name, f.partner_name)
    if concept == "footprint":
        return _activity_identity("footprint", year, program_id, None, state_id, district_id, None,
                                  None, None)
    if concept == "stated_geography":
        return (concept, district_id or state_id)
    if concept == "partner":
        return (*_activity_identity("partner", year, program_id, None, None, None, None, f.project_name,
                                    f.partner_name), f.funder_name)
    if concept == "programme_spend":
        return ("programme", year, f.program_name)
    if concept == "metric":
        return (concept, f.name, f.period, program_id)
    if concept == "contact":
        return (concept, f.name, f.role)
    if concept == "rfp":
        return (concept, f.title, f.deadline)
    if concept == "eligibility_guideline":
        return (concept, f.source_url)
    if concept == "org_identifier":
        return (concept, f.id_type, (f.id_value or "").strip().lower() or None)
    if concept == "org_location":
        return (concept, district_id or state_id)
    if concept == "org_financials":
        return (concept, year)
    return (concept, id(f))


def _describe(concept: str, f: Any) -> str:
    for attr in ("project_name", "partner_name", "title", "name", "sector", "state", "id_type"):
        value = getattr(f, attr, None)
        if value:
            return f"{attr}={value!r}"
    return getattr(f, "fiscal_year", None) or "no distinguishing field"


async def write_facts(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    programs: Programmes, docs: dict[str, int], report: dict[str, Any],
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
    org_names: dict[int, str] = {}
    conflicts: list[Conflict] = []

    async def write(concept: str, f: Any) -> str | None:
        status: str | None = None
        named = getattr(f, "program_name", None)
        program_id = programs.get(named)
        # An NGO's funder line names the funder's programme, which is not this owner's.
        if named and program_id is None and concept != "programme_spend" and owner.column == "funder_id":
            report["held"].append(
                f"{concept} {_describe(concept, f)}: its programme {named!r} is not in Sangam "
                f"({programs.why_not(named)}); held with it rather than written with no programme."
            )
            return None
        document_id = docs.get(f.source_url)
        state_id, district_id = await _place(conn, f, report)
        sector_id = await resolve_csr_sector(conn, getattr(f, "sector", None))
        if sector_id is not None:
            themes.setdefault(sector_id, getattr(f, "sector", "") or "")
        prov = provenance(f, fetched)
        # metric and contact sit on tables with both foreign keys, so
        # they name the entity; the rest are funder-only records.
        base = {"funder_name": name, **prov}
        shared = {"entity_name": name, **prov}

        if concept in ("metric", "contact", "partner") and untiered(
            owner, f, f"{concept} {_describe(concept, f)}", report
        ):
            return None
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
            return None
        seen.add(identity)
        try:
            if concept == "csr_spend":
                domain_id, theme_id, why = await resolve_classification(conn, f.domain, f.theme)
                report["held"].extend(f"csr_spend {_describe(concept, f)}: {r}" for r in why)
                if domain_id is None:
                    return None
                rec = FunderCsrSpendRecord(
                    fiscal_year=f.fiscal_year, amount=f.amount.inr,
                    outlay=f.outlay.inr if f.outlay else None,
                    project_name=f.project_name, project_count=f.project_count,
                    designation=f.designation, partner_name=f.partner_name,
                    partner_csr1=f.partner_csr1, implementation_mode=f.implementation_mode,
                    is_ongoing=f.is_ongoing, domain=f.domain, theme=f.theme,
                    classified_by=f.classified_by, classification_note=f.classification_note,
                    as_of=f.fiscal_year, notes=_with_sector(f), **base,
                )
                status, change = await write_csr_spend(
                    conn, rec, funder_id, program_id=program_id, state_id=state_id,
                    district_id=district_id, csr_sector_id=sector_id,
                    domain_id=domain_id, theme_id=theme_id, document_id=document_id,
                )
                if status == "held":
                    report["held"].append(f"csr_spend {_describe(concept, f)}: {change['reason']}")
                count_write(report, "funder_activity (spend)", status)

            elif concept == "footprint":
                if state_id is None and district_id is None:
                    report["held"].append(
                        f"footprint {f.state!r}: no place to attach it to, and a footprint line "
                        f"needs one"
                    )
                    return None
                rec = FunderFootprintRecord(
                    fiscal_year=f.fiscal_year, state=f.state, district=f.district,
                    name_as_printed=f.name_as_printed or f.district or f.state,
                    notes=f.notes, as_of=f.fiscal_year, **base,
                )
                status, _ = await write_footprint(
                    conn, rec, funder_id, program_id=program_id, state_id=state_id,
                    district_id=district_id, document_id=document_id,
                )
                count_write(report, "funder_activity (footprint)", status)

            elif concept == "stated_geography":
                location_id = district_id or state_id
                if location_id is None:
                    return None
                rec = FunderLocationRecord(
                    state=f.state, district=f.district, role=f.role, note=f.note,
                    as_of=None, **base,
                )
                status, _ = await write_funder_location(
                    conn, rec, funder_id, location_id=location_id, document_id=document_id
                )
                count_write(report, "funder_locations", status)
                if f.role == "registered":
                    await set_registered_location(conn, owner, location_id)

            elif concept == "partner":
                if owner.column == "org_id":
                    # The line is the funder's, so an NGO's record never creates the funder.
                    if not f.funder_name:
                        report["held"].append(
                            f"partner {_describe(concept, f)}: an NGO's funder line needs funder_name, "
                            f"whose money it was"
                        )
                        return None
                    match = await resolve_funder(conn, f.funder_name)
                    if match.method not in MERGEABLE:
                        like = ", ".join(c["name"] for c in match.candidates)
                        report["held"].append(
                            f"partner {f.funder_name!r}: not a funder Sangam holds"
                            + (f" (resembles {like})" if like else "")
                            + ". A person adds or links the funder first."
                        )
                        return None
                    if owner.id not in org_names:
                        found = await (
                            await conn.execute("SELECT name FROM orgs WHERE id = %s", (owner.id,))
                        ).fetchone()
                        org_names[owner.id] = found["name"]
                    catalogued = org_names[owner.id]
                    said = [f.notes]
                    if f.partner_name != catalogued:
                        said.append(f"Named in the source as {f.partner_name!r}.")
                    line_funder, line_program, partner_org_id = match.entity_id, None, owner.id
                    line_name, project = catalogued, f.project_name
                    # The funder's own record of this grant may carry a programme or another title.
                    lines = await _org_line(conn, line_funder, owner.id, f.fiscal_year)
                    if len(lines) > 1:
                        report["held"].append(
                            f"partner {f.funder_name!r} {f.fiscal_year}: the funder already has "
                            f"{len(lines)} lines for this organisation that year ("
                            + ", ".join(f"[activity:{x['id']}]" for x in lines)
                            + "). A person says which one this finding is."
                        )
                        return None
                    if lines:
                        line = lines[0]
                        line_program, line_name, project = (
                            line["program_id"], line["partner_name"], line["project_name"])
                        if f.project_name and project and f.project_name.strip() != project.strip():
                            conflicts.append(Conflict(
                                "funder_activity",
                                f"[activity:{line['id']}] partner {line_name!r} {f.fiscal_year}",
                                "project_name", project, None, None, f.project_name,
                                f.source_type or "unranked", prov.get("source_url")))
                        elif f.project_name and not project:
                            said.append(f"The organisation's source titles it {f.project_name!r}.")
                    names = {"funder_name": f.funder_name, "partner_name": line_name,
                             "partner_canonical": catalogued, "notes": "\n".join(s for s in said if s)}
                else:
                    line_funder, line_program, project = funder_id, program_id, f.project_name
                    org = await _partner_org(conn, f.partner_name)
                    partner_org_id = org[0] if org else None
                    # A catalogued partner is named as Sangam holds it, as 0034 and the seed do.
                    line_name = org[1] if org else f.partner_name
                    said = [f.notes]
                    if line_name != f.partner_name:
                        said.append(f"Named in the source as {f.partner_name!r}.")
                    names = {"funder_name": name, "partner_name": line_name,
                             "partner_canonical": f.partner_canonical or f.partner_name,
                             "notes": "\n".join(s for s in said if s) or None}
                rec = FunderPartnerRecord(
                    fiscal_year=f.fiscal_year, partner_kind=f.partner_kind,
                    partner_csr1=f.partner_csr1, project_name=project,
                    start_date=f.start_date, end_date=f.end_date,
                    relationship_status=f.relationship_status,
                    outlay=f.outlay.inr if f.outlay else None,
                    amount=f.amount.inr if f.amount else None,
                    source_type=f.source_type, evidence_tier=f.evidence_tier,
                    as_of=f.fiscal_year, **names, **prov,
                )
                status, _ = await write_partner(
                    conn, rec, line_funder, program_id=line_program, document_id=document_id,
                    partner_org_id=partner_org_id, fill_only=owner.column == "org_id",
                    conflicts=conflicts,
                )
                count_write(report, "funder_activity (partner)", status)

            elif concept == "programme_spend":
                if program_id is None:
                    report["held"].append(
                        f"programme_spend {f.program_name!r} {f.fiscal_year}: no programme of that "
                        f"name for this funder ({programs.why_not(f.program_name)}), and the funder's own "
                        f"figure has to hang off one."
                    )
                    return None
                domain_id, theme_id, why = await resolve_classification(conn, f.domain, f.theme)
                report["held"].extend(f"programme_spend {f.program_name!r}: {r}" for r in why)
                if domain_id is None:
                    return None
                rec = FunderProgrammeSpendRecord(
                    fiscal_year=f.fiscal_year, program_name=f.program_name, amount=f.amount.inr,
                    domain=f.domain, theme=f.theme, classified_by=f.classified_by,
                    classification_note=f.classification_note, notes=f.notes,
                    as_of=f.fiscal_year, **base,
                )
                status, _ = await write_programme_spend(
                    conn, rec, funder_id, program_id=program_id, domain_id=domain_id,
                    theme_id=theme_id, document_id=document_id,
                )
                count_write(report, "funder_activity (programme)", status)

            elif concept == "metric":
                rec = MetricRecord(
                    name=f.name, value=f.value, target=f.target, unit=f.unit,
                    period=f.period, stage=f.stage, method=f.method,
                    is_self_reported=f.is_self_reported, baseline=f.baseline,
                    comparison_value=f.comparison_value, chain_key=f.chain_key,
                    sequence=f.sequence, notes=f.notes, as_of=f.period,
                    source_type=f.source_type, evidence_tier=f.evidence_tier, **shared,
                )
                status, _ = await write_metric(
                    conn, rec, owner, program_id=program_id,
                    location_id=district_id or state_id, document_id=document_id,
                    conflicts=conflicts,
                )
                count_write(report, "metrics", status)

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
                count_write(report, "rfps", status)

            elif concept == "eligibility_guideline":
                rec = EligibilityGuidelineRecord(
                    title=f.title, statutory_restatement=f.statutory_restatement,
                    own_bar=f.own_bar, disqualifiers=f.disqualifiers, not_stated=f.not_stated,
                    as_of=f.as_of, **base,
                )
                _, status = await write_eligibility_document(conn, rec, funder_id)
                count_write(report, "documents (funder_eligibility)", status)

            elif concept == "org_identifier":
                rec = OrgIdentifierRecord(
                    entity_name=name, id_type=f.id_type, id_value=f.id_value, status=f.status,
                    valid_from=f.valid_from, valid_until=f.valid_until, check_method=f.check_method,
                    application_ref=f.application_ref, notes=f.notes, source_type=f.source_type,
                    evidence_tier=f.evidence_tier, as_of=None, **prov,
                )
                status, _, found = await write_org_identifier(conn, rec, owner.id, document_id)
                conflicts.extend(found)
                count_write(report, "org_identifiers", status)

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
                    foreign_unspent=f.foreign_unspent.inr if f.foreign_unspent else None,
                    is_audited=f.is_audited, notes=f.notes, as_of=f.fiscal_year,
                    source_type=f.source_type, evidence_tier=f.evidence_tier, **shared,
                )
                status, _, found = await write_org_financials(
                    conn, rec, owner.id, document_id
                )
                conflicts.extend(found)
                count_write(report, "org_financials", status)

            elif concept == "org_location":
                location_id = district_id or state_id
                if location_id is None:
                    return None
                rec = OrgLocationRecord(
                    state=f.state, district=f.district, role=f.role, program_name=f.program_name, note=f.note,
                    source_type=f.source_type, evidence_tier=f.evidence_tier, as_of=None, **shared,
                )
                status, _, found = await write_org_location(
                    conn, rec, owner.id, location_id=location_id, document_id=document_id,
                    program_id=program_id,
                )
                conflicts.extend(found)
                count_write(report, "org_locations", status)
                # A registered address is this concept with role='registered',
                # not a second field on org_identity — so the column that
                # names it is set here, where the place is already resolved.
                if f.role == "registered":
                    await set_registered_location(conn, owner, location_id)

            elif concept == "contact":
                rec = ContactRecord(
                    name=f.name, contact_kind=f.kind, role=f.role, email=f.email,
                    is_role_mailbox=f.is_role_mailbox, notes=f.notes, as_of=None,
                    source_type=f.source_type, evidence_tier=f.evidence_tier, **shared,
                )
                status, _ = await write_contact(
                    conn, rec, owner, document_id=document_id, conflicts=conflicts
                )
                count_write(report, "contacts", status)

        except ValidationError as exc:
            report["held"].append(f"{concept}: {exc.errors()[0]['msg']}")
        return status

    for concept in order:
        for f in validated(findings, concept, report):
            mark = Mark(report, conflicts)
            mark.settle(f, await write(concept, f))
    report["conflicts"].extend(c.describe() for c in conflicts)

    # Every Schedule VII clause this funder's spending touched, recorded once
    # against the funder with the wording that placed it there. org_tags is
    # not a concept, and nothing on the org side resolves a sector anyway.
    for tag_id, wording in themes.items() if owner.column == "funder_id" else ():
        await write_funder_tag(
            conn, funder_id, tag_id, note=f"from research: {wording}" if wording else None
        )


def _with_sector(f: Any) -> str | None:
    """The sector as filed, in the funder's own words, kept in notes beside whatever csr_sector_id
    resolved to: "Building Human Capital" is not Education until someone decides it is."""
    bits = [b for b in (f.sector, f.notes) if b]
    return " · ".join(bits) or None
