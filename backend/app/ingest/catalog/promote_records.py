"""What promote builds from a researcher's findings: the funder, org and CSR-year records, and the report it keeps."""

from __future__ import annotations

import collections
import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from app.ingest.brief import fact_key
from app.ingest.catalog.rows import (
    CIN_FORMAT,
    ContactRecord,
    EligibilityGuidelineRecord,
    FunderCsrSpendRecord,
    FunderCsrYearRecord,
    FunderFootprintRecord,
    FunderLocationRecord,
    FunderPartnerRecord,
    FunderProgrammeSpendRecord,
    FunderRecord,
    MetricRecord,
    OrgFinancialsRecord,
    OrgIdentifierRecord,
    OrgLocationRecord,
    OrgRecord,
    ProgramRecord,
    RfpRecord,
    fiscal_year_of,
    http_url,
    normalise_cin,
)
from app.ingest.catalog.writer import SOURCE_PRECEDENCE, Conflict, Owner, write_tags
from app.ingest.research.finding_types import FINDING_MODELS, MAX_THEMES, SCHEMA_VERSION, to_inr
from app.ingest.taxonomy import TAG_KINDS

logger = logging.getLogger(__name__)


# The matcher methods that mean "this is the same organisation". 'trigram'
# proposes and a person accepts; 'none' is a new entity.
MERGEABLE = ("identifier", "exact", "alias", "boilerplate", "website")


# Only a match made on the name makes the research's spelling an alias; a number match says nothing of names.
NAME_MATCHES = ("exact", "alias", "boilerplate")


# A number resolves an org only when a finding says it is a live registration, not a listing that was not found.
MATCHING_STATUSES = frozenset({"registered", "provisional"})


# Documents first, so every other fact can cite the report it was read from.
# Programmes next, because every remaining concept can name one and a spend row
# whose program_id is null for want of ordering is a quietly weaker row.
WRITE_ORDER = (
    "csr_spend", "footprint", "stated_geography", "partner", "programme_spend", "metric", "contact",
    "rfp", "eligibility_guideline",
)


# The org side's own order. Separate rather than appended: the funder path
# would otherwise try concepts whose findings it never has, and the shared
# concepts — programme, metric, contact, document — are the only overlap.
# Identifiers first: each is its own fact with its own source, and nothing else names one.
ORG_WRITE_ORDER = ("org_identifier", "org_financials", "org_location", "metric", "contact", "partner")


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
    "csr_year": FunderCsrYearRecord,
    "csr_spend": FunderCsrSpendRecord,
    "footprint": FunderFootprintRecord,
    "stated_geography": FunderLocationRecord,
    "partner": FunderPartnerRecord,
    "programme_spend": FunderProgrammeSpendRecord,
    "program": ProgramRecord,
    "metric": MetricRecord,
    "contact": ContactRecord,
    "rfp": RfpRecord,
    "eligibility_guideline": EligibilityGuidelineRecord,
    "org_identity": OrgRecord,
    "org_identifier": OrgIdentifierRecord,
    "org_financials": OrgFinancialsRecord,
    "org_location": OrgLocationRecord,
}


# A finding field whose record field has a different name. `kind` collides
# with the records' own discriminator, hence the prefixes.
RENAMED: dict[tuple[str, str], str] = {
    ("program", "kind"): "program_kind",
    ("contact", "kind"): "contact_kind",
}


def provenance(finding: dict[str, Any] | Any, fetched: datetime) -> dict[str, Any]:
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


def untiered(owner: Owner, f: Any, what: str, report: dict[str, Any]) -> bool:
    """An organisation's programme, metric or contact needs its tier; a funder's has none."""
    if owner.column != "org_id" or (getattr(f, "source_type", None) and getattr(f, "evidence_tier", None)):
        return False
    report["held"].append(
        f"{what}: an organisation's finding needs source_type and evidence_tier. It stays on the research "
        f"row; re-research it to promote it."
    )
    return True


def validated(
    findings: list[dict[str, Any]], concept: str, report: dict[str, Any] | None = None
) -> list[Any]:
    """Findings come back out of jsonb as plain dicts; re-validating lets the writers map, not parse.
    A finding refused here goes into report["held"], or it would be a fact that silently never lands."""
    out = []
    for f in findings:
        if f.get("concept") != concept:
            continue
        try:
            model = FINDING_MODELS[concept].model_validate(f)
        except ValidationError as exc:
            err = exc.errors()[0]
            where = ".".join(str(p) for p in err.get("loc", ())) or "finding"
            msg = f"{concept} finding refused ({where}): {err.get('msg')}"
            logger.info(msg)
            if report is not None:
                report["held"].append(
                    f"{msg}. It stays on the research row; re-research it in the current shape to promote it."
                )
                settle(report, f, {"state": "held", "reason": msg})
            continue
        if report is not None:
            # The fact as the brief keys it: validation may reshape a value the key is built from.
            report.setdefault("_raw", {})[id(model)] = f
        out.append(model)
    return out


def count_write(report: dict[str, Any], table: str, status: str) -> None:
    if status in ("added", "updated"):
        report["written"].setdefault(table, collections.Counter())[status] += 1


# A writer's status, as the brief says it.
STATES = {"added": "written", "updated": "written", "planned": "written", "matched": "confirms",
          "asked": "waiting", "kept": "kept", "skipped": "skipped"}


def settle(report: dict[str, Any], raw: dict[str, Any], state: dict[str, Any]) -> None:
    report.setdefault("facts", {})[json.dumps(list(fact_key(raw)))] = state


def settle_identity(report: dict[str, Any], findings: list[dict[str, Any]], concept: str, status: str,
                     row: str) -> None:
    for f in findings:
        if f.get("concept") == concept and status in STATES:
            settle(report, f, {"state": STATES[status], **({"row": row} if "-1" not in row else {})})


def guarded(report: dict[str, Any], findings: list[dict[str, Any]],
             held: tuple[list[dict[str, Any]], list[str]]) -> list[dict[str, Any]]:
    """What a source guard let through; each fact it held gets the guard's reasons as its state."""
    kept, reasons = held
    report["held"].extend(reasons)
    passed = {id(f) for f in kept}
    for f in findings:
        if id(f) not in passed and f.get("concept"):
            settle(report, f, {"state": "held", "reason": " ".join(dict.fromkeys(reasons))})
    return kept


def unsettled(report: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Every fact ends in a state: one no writer reached says why, from the promotion's own reasons."""
    why = (" ".join(report["reasons"]) if report["entity"] is None else "") or "promotion did not reach it"
    for f in findings:
        if not f.get("concept") or json.dumps(list(fact_key(f))) in report.get("facts", {}):
            continue
        if f["concept"] in report["skipped"]:
            state = {"state": "no column", "reason": "Sangam has no table for this yet"}
        else:
            state = {"state": "held", "reason": why}
        settle(report, f, state)


class Mark:
    """What one fact became, read off its status or the held and conflict lines it added."""

    def __init__(self, report: dict[str, Any], conflicts: list[Conflict] | None = None) -> None:
        self.report, self.conflicts = report, conflicts if conflicts is not None else []
        self.held, self.found = len(report["held"]), len(self.conflicts)

    def settle(self, f: Any, status: str | None, row: str | None = None) -> None:
        raw = self.report.get("_raw", {}).get(id(f))
        if raw is None:
            return
        found = self.conflicts[self.found:]
        held = self.report["held"][self.held:]
        if found:
            state = {"state": "conflicts", "reason": "; ".join(c.describe() for c in found)}
        elif status in STATES:
            state = {"state": STATES[status], **({"row": row} if row else {})}
        else:
            state = {"state": "held", "reason": " ".join(held) or "not written, and no reason was recorded"}
        settle(self.report, raw, state)


# Concepts from before 0031 and 0034 that promotion still reads, so they are not reported as "no writer".
FOLDED = frozenset({"identifier", "grant"})


def _legacy_identifiers(findings: list[dict[str, Any]]) -> dict[str, list[str]]:
    """`identifier` findings saved before 0031, by type. Only cin, name and domain have a home now (D1)."""
    out: dict[str, list[str]] = {}
    for f in findings:
        if f.get("concept") == "identifier" and f.get("id_value"):
            out.setdefault(f.get("id_type") or "", []).append(str(f["id_value"]).strip())
    return out


def legacy_grants(findings: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """`grant` findings saved before 0034, as the partner findings they are now; one with no date or a
    non-INR amount cannot be placed and is held, as 0034 refuses the same rows."""
    out: list[dict[str, Any]] = []
    for f in findings:
        if f.get("concept") != "grant":
            continue
        when = f.get("start_date") or f.get("end_date")
        why = None
        if not when:
            why = "no start or end date, so no fiscal year for its partner line"
        elif f.get("amount") and (f.get("currency") or "INR") != "INR":
            why = f"an amount in {f.get('currency')}, and a partner line's amount is INR"
        if why:
            report["held"].append(
                f"grant {f.get('title')!r} (saved before 0034): {why}. Re-research it as a partner finding."
            )
            continue
        out.append({
            "concept": "partner", "fiscal_year": fiscal_year_of(date.fromisoformat(str(when)[:10])),
            "partner_name": f.get("recipient_name"), "project_name": f.get("title"),
            "relationship_status": f.get("status"), "amount": f.get("amount"),
            "start_date": f.get("start_date"), "end_date": f.get("end_date"),
            "program_name": f.get("program_name"),
            "notes": "\n".join(n for n in (f.get("notes"), None if f.get("start_date") else
                                "fiscal_year is the year of the end date; the start date was not stated.") if n)
            or None,
            **{k: f[k] for k in ("evidence", "source_url", "source_name", "confidence", "basis") if k in f},
        })
    return out


def _with_scheme(domain: str) -> str:
    """A legacy domain as a website; one already carrying http(s):// is kept as is (0031 does the same)."""
    return domain if domain.lower().startswith(("http://", "https://")) else f"https://{domain}"


# Identity fields that are lists, unioned across findings; the rest take one value, and these say where from.
_IDENTITY_LISTS = ("aliases", *TAG_KINDS)


_IDENTITY_META = frozenset({"concept", "evidence", "source_url", "source_name", "confidence", "basis", "page",
                            "source_type", "evidence_tier", "tag_note"})


def _source_rank(f: dict[str, Any]) -> tuple[int, bool]:
    """An org finding's source as write_org ranks it; a funder's identity has no tier, so all tie and order rules."""
    return SOURCE_PRECEDENCE.get(f.get("source_type"), 0), f.get("evidence_tier") == "evidenced"


def merged_identity(
    findings: list[dict[str, Any]], concept: str, report: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Every identity finding as one (fields, anchor): lists unioned, each other field from the strongest source
    stating it. The anchor is the weakest source a field came from, so the record never outranks a value it holds."""
    ranked = sorted((f for f in findings if f.get("concept") == concept), key=_source_rank, reverse=True)
    if not ranked:
        return None
    reasons = report["reasons"] if report is not None else []
    fields: dict[str, Any] = {k: [] for k in _IDENTITY_LISTS}
    used = [ranked[0]]
    for f in ranked:
        for k, v in f.items():
            if k in _IDENTITY_META or v is None or v == "" or v == []:
                continue
            if k in _IDENTITY_LISTS:
                fields[k].extend(x for x in v if x not in fields[k])
            elif k not in fields:
                fields[k] = v
                if f not in used:
                    used.append(f)
            elif str(v).strip().lower() != str(fields[k]).strip().lower():
                if k == "name" and v not in fields["aliases"]:
                    fields["aliases"].append(v)
                reasons.append(f"{concept}: {k} {fields[k]!r} kept over {v!r} ({f.get('source_url')})")
    reasons.extend(f"{concept}: theme {t!r} not tagged (at most {MAX_THEMES})" for t in fields["themes"][MAX_THEMES:])
    fields["themes"] = fields["themes"][:MAX_THEMES]
    notes = dict.fromkeys(n.strip() for f in ranked if (n := f.get("tag_note")) and n.strip())
    fields["tag_note"] = " · ".join(notes) or None
    return fields, min(used, key=_source_rank)


def funder_from(row: dict[str, Any], findings: list[dict[str, Any]],
                report: dict[str, Any] | None = None) -> FunderRecord | None:
    """One funder record, from every identity finding and any identifiers saved before 0031."""
    merged = merged_identity(findings, "identity", report)
    identity, first = merged if merged else (None, None)
    legacy = [f for f in findings if f["concept"] == "identifier"]
    anchor = first or (legacy[0] if legacy else None)
    if anchor is None:
        return None
    ident = identity or {}
    old = _legacy_identifiers(legacy)
    cins = [c for c in map(normalise_cin, old.get("cin", [])) if CIN_FORMAT.fullmatch(c)]
    domains = old.get("domain", [])
    try:
        return FunderRecord(
            name=ident.get("name") or row["canonical_name"] or row["entity_name"],
            funder_type=ident.get("funder_type"),
            website=ident.get("website") or row.get("website")
            or (_with_scheme(domains[0]) if domains else None),
            section_135_bound=ident.get("section_135_bound"),
            parent_name=ident.get("parent_name"),
            cin=ident.get("cin") or (cins[0] if cins else None),
            aliases=[*(ident.get("aliases") or []), *old.get("name", [])],
            intake_mode=ident.get("intake_mode"),
            funds_external=ident.get("funds_external"),
            typical_duration_months=ident.get("typical_duration_months"),
            grant_size_min=to_inr(ident.get("grant_size_min")),
            grant_size_max=to_inr(ident.get("grant_size_max")),
            legal_form=ident.get("legal_form"),
            founded_year=ident.get("founded_year"),
            registered_address=ident.get("registered_address"),
            as_of=ident.get("as_of"),
            **_tags(ident),
            **provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("funder record refused for %s: %s", row["slug"], exc)
        return None


def _tags(finding: dict[str, Any]) -> dict[str, Any]:
    return {k: finding.get(k) or [] for k in TAG_KINDS} | {"tag_note": finding.get("tag_note")}


async def write_record_tags(conn: Any, column: str, subject_id: int | None, rec: Any, what: str,
                      report: dict[str, Any]) -> None:
    if subject_id is None:
        return
    added, reasons = await write_tags(conn, column, subject_id, rec)
    if added:
        report["written"].setdefault("tags", collections.Counter())["added"] += added
    report["reasons"].extend(f"{what}: {r}" for r in reasons)


def _http_only(url: str | None) -> str | None:
    """The research envelope's website, only when it is http(s); anything else must not refuse the org."""
    try:
        return http_url(url)
    except ValueError:
        return None


def org_from(row: dict[str, Any], findings: list[dict[str, Any]],
             report: dict[str, Any] | None = None) -> OrgRecord | None:
    """One org record, the same shape as funder_from; the anchor finding's tier ranks the write."""
    merged = merged_identity(findings, "org_identity", report)
    identity, first = merged if merged else (None, None)
    identifiers = [f for f in findings if f["concept"] == "org_identifier"]
    anchor = first or (identifiers[0] if identifiers else None)
    if anchor is None:
        return None
    ident = identity or {}
    try:
        return OrgRecord(
            name=ident.get("name") or row["canonical_name"] or row["entity_name"],
            org_kind=ident.get("org_kind"),
            legal_form=ident.get("legal_form"),
            registration_date=ident.get("registration_date"),
            registered_address=ident.get("registered_address"),
            parent_name=ident.get("parent_name"),
            website=ident.get("website") or _http_only(row.get("website")),
            description=ident.get("description"),
            aliases=ident.get("aliases") or [],
            staff_count=ident.get("staff_count"),
            staff_count_note=ident.get("staff_count_note"),
            **_tags(ident),
            identifiers={f["id_type"]: f["id_value"] for f in identifiers
                         if f.get("id_value") and f.get("status") in MATCHING_STATUSES},
            source_type=anchor.get("source_type"),
            evidence_tier=anchor.get("evidence_tier"),
            as_of=None,
            **provenance(anchor, row["researched_at"]),
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
                    local_area_spent=to_inr(f.get("local_area_spent")),
                    impact_assessment_done=f.get("impact_assessment_done"),
                    section_135_applicable=f.get("section_135_applicable"),
                    notes=f.get("notes") or f"Promoted from research: {f.get('evidence', '')[:200]}",
                    as_of=f["fiscal_year"],
                    **provenance(f, row["researched_at"]),
                )
            )
        except ValueError as exc:
            logger.info("csr year refused for %s %s: %s", row["slug"], f.get("fiscal_year"), exc)
    return out
