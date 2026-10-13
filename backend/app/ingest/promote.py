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
import json
import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from app.ingest import source_guards, staff_sources, vault
from app.ingest.brief import fact_key
from app.ingest.expectations import PROMOTABLE, activity_kind
from app.ingest.geography import resolve_location
from app.ingest.matcher import Match, _is_foundation, name_key, resolve_funder, resolve_org, variants
from app.ingest.records import (
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
from app.ingest.research_records import FINDING_MODELS, SCHEMA_VERSION, TYPED_SINCE, to_inr
from app.ingest.taxonomy import TAG_KINDS, resolve_classification, resolve_csr_sector
from app.ingest.writer import (
    GATE,
    UNWRITTEN,
    Conflict,
    Gate,
    Owner,
    cin_holder,
    ensure_document,
    org_alias_holders,
    set_registered_location,
    write_contact,
    write_csr_spend,
    write_csr_year,
    write_eligibility_document,
    write_footprint,
    write_funder,
    write_funder_location,
    write_funder_tag,
    write_metric,
    write_org,
    write_org_financials,
    write_org_identifier,
    write_org_location,
    write_partner,
    write_program,
    write_programme_spend,
    write_rfp,
    write_tags,
)
from app.integrations import storage

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


def _untiered(owner: Owner, f: Any, what: str, report: dict[str, Any]) -> bool:
    """An organisation's programme, metric or contact needs its tier; a funder's has none."""
    if owner.column != "org_id" or (getattr(f, "source_type", None) and getattr(f, "evidence_tier", None)):
        return False
    report["held"].append(
        f"{what}: an organisation's finding needs source_type and evidence_tier. It stays on the research "
        f"row; re-research it to promote it."
    )
    return True


def _validated(
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
                _settle(report, f, {"state": "held", "reason": msg})
            continue
        if report is not None:
            # The fact as the brief keys it: validation may reshape a value the key is built from.
            report.setdefault("_raw", {})[id(model)] = f
        out.append(model)
    return out


def _count(report: dict[str, Any], table: str, status: str) -> None:
    if status in ("added", "updated"):
        report["written"].setdefault(table, collections.Counter())[status] += 1


# A writer's status, as the brief says it.
STATES = {"added": "written", "updated": "written", "planned": "written", "matched": "confirms",
          "asked": "waiting", "kept": "kept", "skipped": "skipped"}


def _settle(report: dict[str, Any], raw: dict[str, Any], state: dict[str, Any]) -> None:
    report.setdefault("facts", {})[json.dumps(list(fact_key(raw)))] = state


def _settle_identity(report: dict[str, Any], findings: list[dict[str, Any]], concept: str, status: str,
                     row: str) -> None:
    for f in findings:
        if f.get("concept") == concept and status in STATES:
            _settle(report, f, {"state": STATES[status], **({"row": row} if "-1" not in row else {})})


def _guarded(report: dict[str, Any], findings: list[dict[str, Any]],
             held: tuple[list[dict[str, Any]], list[str]]) -> list[dict[str, Any]]:
    """What a source guard let through; each fact it held gets the guard's reasons as its state."""
    kept, reasons = held
    report["held"].extend(reasons)
    passed = {id(f) for f in kept}
    for f in findings:
        if id(f) not in passed and f.get("concept"):
            _settle(report, f, {"state": "held", "reason": " ".join(dict.fromkeys(reasons))})
    return kept


def _unsettled(report: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Every fact ends in a state: one no writer reached says why, from the promotion's own reasons."""
    why = (" ".join(report["reasons"]) if report["entity"] is None else "") or "promotion did not reach it"
    for f in findings:
        if not f.get("concept") or json.dumps(list(fact_key(f))) in report.get("facts", {}):
            continue
        if f["concept"] in report["skipped"]:
            state = {"state": "no column", "reason": "Sangam has no table for this yet"}
        else:
            state = {"state": "held", "reason": why}
        _settle(report, f, state)


class _Mark:
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
        _settle(self.report, raw, state)


# Concepts from before 0031 and 0034 that promotion still reads, so they are not reported as "no writer".
FOLDED = frozenset({"identifier", "grant"})


def _legacy_identifiers(findings: list[dict[str, Any]]) -> dict[str, list[str]]:
    """`identifier` findings saved before 0031, by type. Only cin, name and domain have a home now (D1)."""
    out: dict[str, list[str]] = {}
    for f in findings:
        if f.get("concept") == "identifier" and f.get("id_value"):
            out.setdefault(f.get("id_type") or "", []).append(str(f["id_value"]).strip())
    return out


def _legacy_grants(findings: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
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


def _with_scheme(domain: str) -> str:
    """A legacy domain as a website; one already carrying http(s):// is kept as is (0031 does the same)."""
    return domain if domain.lower().startswith(("http://", "https://")) else f"https://{domain}"


def funder_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> FunderRecord | None:
    """One funder record, from the identity finding and any identifiers saved before 0031."""
    identity = next((f for f in findings if f["concept"] == "identity"), None)
    legacy = [f for f in findings if f["concept"] == "identifier"]
    anchor = identity or (legacy[0] if legacy else None)
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
            **_provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("funder record refused for %s: %s", row["slug"], exc)
        return None


def _tags(finding: dict[str, Any]) -> dict[str, Any]:
    return {k: finding.get(k) or [] for k in TAG_KINDS} | {"tag_note": finding.get("tag_note")}


async def _write_tags(conn: Any, column: str, subject_id: int | None, rec: Any, what: str,
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


def org_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> OrgRecord | None:
    """One org record, the same shape as funder_from; the anchor finding's tier ranks the write."""
    identity = next((f for f in findings if f["concept"] == "org_identity"), None)
    identifiers = [f for f in findings if f["concept"] == "org_identifier"]
    anchor = identity or (identifiers[0] if identifiers else None)
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
                    local_area_spent=to_inr(f.get("local_area_spent")),
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
    for f in _validated(findings, "document", report):
        mark = _Mark(report)
        if staff_sources.is_staff_source_url(f.source_url) or vault.is_vault_url(f.source_url):
            # the private row exists; ensure_document would add a public one
            report["held"].append("document: skipped: private document already on file")
            mark.settle(f, "skipped")
            continue
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
        mark.settle(f, status, f"[documents:{document_id}]")
    by_url.update(await _staff_datasets(conn, findings))
    by_url.update(await vault.document_rows(conn, findings))
    return by_url


async def _staff_datasets(conn: Any, findings: list[dict[str, Any]]) -> dict[str, int]:
    """source_url -> the private row of each staff dataset cited, so its lines carry document_id."""
    return {url: row["id"] for url, row in (await _staff_dataset_rows(conn, findings)).items()}


async def _staff_dataset_rows(conn: Any, findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """source_url -> the staff dataset row it names, with what is needed to re-open the workbook."""
    urls = sorted({
        f["source_url"] for f in findings if staff_sources.is_staff_source_url(f.get("source_url"))
    })
    if not urls:
        return {}
    rows = await (await conn.execute(
        "SELECT id, source_url, source_name, storage_path, content_hash FROM documents "
        "WHERE doc_type = 'source_dataset' AND source_url = ANY(%s) ORDER BY id",
        (urls,),
    )).fetchall()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        found.setdefault(row["source_url"], dict(row))
    return found


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


# "Mission 2 Million (2019-2025)"; "SLP - Rural Livelihoods"; "Rural Livelihoods (SLP component)".
_PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")
_PREFIX = re.compile(r"^([A-Z][A-Z0-9&]{1,9})\s*[-–:]\s+(.+)$")
_SMALL = frozenset({"of", "the", "and", "for", "in", "a"})


def programme_key(name: str) -> str:
    """A programme's name as it is matched: no trailing parenthetical, no `ABBR - ` prefix."""
    bare = _PAREN.sub("", name).strip() or name
    m = _PREFIX.match(bare)
    return name_key(m[2] if m else bare)


def _abbreviation(name: str) -> str | None:
    """The parent a spend line names by its initials: SLP in "SLP - Rural Livelihoods" or "(SLP component)"."""
    bare = _PAREN.sub("", name).strip()
    if m := _PREFIX.match(bare):
        return m[1]
    paren = _PAREN.search(name)
    word = paren and re.match(r"([A-Z][A-Z0-9&]{1,9})\b", paren[1])
    return word[1] if word else None


def _initials(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in _SMALL).upper()


class Programmes:
    """One owner's programmes by programme_key: those written this run, then those already stored."""

    def __init__(self, stored: dict[str, tuple[int, str]]) -> None:
        self.stored = stored
        self.ids: dict[str, int] = {}
        self.names: dict[str, str] = {}
        self.held: dict[str, str] = {}

    @classmethod
    async def load(cls, conn: Any, owner: Owner) -> Programmes:
        rows = await (await conn.execute(
            f"SELECT id, name FROM programs WHERE {owner.column} = %s ORDER BY id", (owner.id,)
        )).fetchall()
        stored: dict[str, tuple[int, str]] = {}
        for r in rows:
            stored.setdefault(programme_key(r["name"]), (r["id"], r["name"]))
        return cls(stored)

    def get(self, name: str | None, default: int | None = None) -> int | None:
        if not name:
            return default
        key = programme_key(name)
        if key in self.ids:
            return self.ids[key]
        return self.stored[key][0] if key in self.stored else default

    def name(self, name: str) -> str:
        """The spelling the row has, or will have: a stored or just-written one wins over this one."""
        key = programme_key(name)
        return self.names.get(key) or (self.stored[key][1] if key in self.stored else name)

    def why_not(self, name: str) -> str:
        return self.held.get(programme_key(name)) or "no programme of that name was researched or is held"

    def by_initials(self, abbreviation: str) -> tuple[int, str] | None:
        found = {(i, n) for k, i in self.ids.items() if _initials(n := self.names[k]) == abbreviation}
        found |= {v for v in self.stored.values() if _initials(v[1]) == abbreviation}
        return found.pop() if len(found) == 1 else None


def _parents_first(found: list[Any]) -> list[Any]:
    """Shallowest kind first, and a programme after the programme it names as parent, whatever their kinds."""
    depth = {"theme": 0, "programme": 1, "component": 2, "phase": 2, "project": 3}
    pending = sorted(found, key=lambda f: depth.get(f.kind, 9))
    out: list[Any] = []
    while pending:
        waiting = {programme_key(f.name) for f in pending}
        ready = [f for f in pending if not f.parent_name or programme_key(f.parent_name) not in waiting
                 or programme_key(f.parent_name) == programme_key(f.name)]
        ready = ready or pending[:1]  # a cycle: write one, and its parent lookup decides
        out += ready
        pending = [f for f in pending if f not in ready]
    return out


async def _write_programs(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    docs: dict[str, int], report: dict[str, Any],
) -> Programmes:
    """Every programme, parents first, so later concepts can resolve program_name; a held parent holds its children."""
    programs = await Programmes.load(conn, owner)
    conflicts: list[Conflict] = []
    for f in _parents_first(_validated(findings, "program", report)):
        mark = _Mark(report, conflicts)
        key = programme_key(f.name)
        if key in programs.names:
            # "Mission 2 Million (2019-2025)" after "Mission 2 Million": one programme, written once.
            mark.settle(f, "matched", f"[programs:{programs.ids[key]}]" if programs.ids[key] != UNWRITTEN else None)
            continue
        if _untiered(owner, f, f"programme {f.name!r}", report):
            programs.held[key] = "its own finding has no evidence tier"
            mark.settle(f, None)
            continue
        parent_id = programs.get(f.parent_name)
        if f.parent_name and parent_id is None:
            why = f"its parent {f.parent_name!r} is not in Sangam ({programs.why_not(f.parent_name)})"
            report["held"].append(f"programme {f.name!r}: {why}; held with it rather than written with no parent.")
            programs.held[key] = why
            mark.settle(f, None)
            continue
        status, program_id = await _write_program(
            conn, row, f, programs.name(f.name), f.kind, parent_id, owner, docs, report, conflicts)
        if program_id is None:
            programs.held[key] = "it is waiting for a person" if status == "asked" else "it was not written"
        else:
            programs.ids[key], programs.names[key] = program_id, programs.name(f.name)
        mark.settle(f, status, f"[programs:{program_id}]" if program_id not in (None, UNWRITTEN) else None)
    await _write_components(conn, row, findings, owner, programs, docs, report, conflicts)
    report["conflicts"].extend(c.describe() for c in conflicts)
    return programs


async def _write_program(
    conn: Any, row: dict[str, Any], f: Any, name: str, kind: str, parent_id: int | None, owner: Owner,
    docs: dict[str, int], report: dict[str, Any], conflicts: list[Conflict],
) -> tuple[str | None, int | None]:
    try:
        rec = ProgramRecord(
            entity_name=row["canonical_name"] or row["entity_name"], name=name,
            program_kind=kind, description=getattr(f, "description", None), status=getattr(f, "status", None),
            start_date=getattr(f, "start_date", None), end_date=getattr(f, "end_date", None),
            is_enabler=getattr(f, "is_enabler", None),
            themes=getattr(f, "themes", None) or [], populations=getattr(f, "populations", None) or [],
            lenses=getattr(f, "lenses", None) or [], tag_note=getattr(f, "tag_note", None),
            source_type=getattr(f, "source_type", None), evidence_tier=getattr(f, "evidence_tier", None),
            as_of=None, **_provenance(f, row["researched_at"]),
        )
    except ValidationError as exc:
        report["held"].append(f"programme {name!r}: {exc.errors()[0]['msg']}")
        return None, None
    status, program_id, _ = await write_program(
        conn, rec, owner, parent_id=parent_id, document_id=docs.get(f.source_url), conflicts=conflicts,
    )
    _count(report, "programs", status)
    await _write_tags(conn, "program_id", program_id, rec, f"programme {name!r}", report)
    return status, program_id


async def _write_components(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner, programs: Programmes,
    docs: dict[str, int], report: dict[str, Any], conflicts: list[Conflict],
) -> None:
    """A spend line naming no programme, but its parent by initials, is a component of that parent.
    "SLP - Ecosystem Action" with no such programme becomes "Ecosystem Action" under Sustainable Livelihood Programme."""
    for f in _validated([f for f in findings if f.get("concept") == "programme_spend"], "programme_spend"):
        if programs.get(f.program_name) is not None or not (abbreviation := _abbreviation(f.program_name)):
            continue
        parent = programs.by_initials(abbreviation)
        if parent is None:
            continue
        key = programme_key(f.program_name)
        name = _PREFIX.sub(r"\2", _PAREN.sub("", f.program_name).strip())
        _, program_id = await _write_program(
            conn, row, f, name, "component", parent[0], owner, docs, report, conflicts)
        if program_id is not None:
            programs.ids[key], programs.names[key] = program_id, name


def _activity_identity(
    kind: str, year: str | None, program_id: int | None, sector_id: int | None,
    state_id: int | None, location_id: int | None, designation: str | None,
    project_name: str | None, partner_name: str | None,
) -> tuple:
    """writer.FUNDER_ACTIVITY_KEY without funder_id, in its order."""
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


async def _write_facts(
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
        prov = _provenance(f, fetched)
        # metric and contact sit on tables with both foreign keys, so
        # they name the entity; the rest are funder-only records.
        base = {"funder_name": name, **prov}
        shared = {"entity_name": name, **prov}

        if concept in ("metric", "contact", "partner") and _untiered(
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
                _count(report, "funder_activity (spend)", status)

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
                _count(report, "funder_activity (footprint)", status)

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
                _count(report, "funder_locations", status)
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
                _count(report, "funder_activity (partner)", status)

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
                _count(report, "funder_activity (programme)", status)

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

            elif concept == "eligibility_guideline":
                rec = EligibilityGuidelineRecord(
                    title=f.title, statutory_restatement=f.statutory_restatement,
                    own_bar=f.own_bar, disqualifiers=f.disqualifiers, not_stated=f.not_stated,
                    as_of=f.as_of, **base,
                )
                _, status = await write_eligibility_document(conn, rec, funder_id)
                _count(report, "documents (funder_eligibility)", status)

            elif concept == "org_identifier":
                rec = OrgIdentifierRecord(
                    entity_name=name, id_type=f.id_type, id_value=f.id_value, status=f.status,
                    valid_from=f.valid_from, valid_until=f.valid_until, check_method=f.check_method,
                    application_ref=f.application_ref, notes=f.notes, source_type=f.source_type,
                    evidence_tier=f.evidence_tier, as_of=None, **prov,
                )
                status, _, found = await write_org_identifier(conn, rec, owner.id, document_id)
                conflicts.extend(found)
                _count(report, "org_identifiers", status)

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
                _count(report, "org_financials", status)

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
                _count(report, "org_locations", status)
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
                _count(report, "contacts", status)

        except ValidationError as exc:
            report["held"].append(f"{concept}: {exc.errors()[0]['msg']}")
        return status

    for concept in order:
        for f in _validated(findings, concept, report):
            mark = _Mark(report, conflicts)
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


async def _org_parent(conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]) -> int | None:
    """The parent body's org id when Sangam holds it; otherwise a held line, never a new row."""
    if not record.parent_name:
        return None
    parent = await resolve_org(conn, record.parent_name)
    if parent.method in MERGEABLE and parent.entity_id != match.entity_id:
        return parent.entity_id
    report["held"].append(
        f"parent {record.parent_name!r} of {record.name!r} is not an organisation Sangam holds, so the link "
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


async def _reconcile_org_aliases(
    conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]
) -> OrgRecord:
    """Aliases to add: the research's own spelling (on a matched org) and its aliases, less any another
    organisation already answers to. Those are held: a shared spelling resolves neither org."""
    by_name = match.method in NAME_MATCHES
    wanted = [*([record.name] if by_name else []), *record.aliases]
    holders = await org_alias_holders(conn, wanted, match.entity_id)
    for spelling in wanted:
        holder = holders.get(name_key(spelling))
        if holder is not None:
            report["held"].append(
                f"alias {spelling!r} is already the name or an alias of {holder['name']!r} "
                f"[org:{holder['id']}], so it is not added to {record.name!r}. Two organisations "
                f"sharing a spelling is a decision for a person."
            )
    kept = [s for s in wanted if name_key(s) not in holders]
    return record.model_copy(update={"aliases": kept})


async def _reconcile_with_stored(
    conn: Any, record: FunderRecord, match: Match, report: dict[str, Any]
) -> FunderRecord:
    """Drop what the funders row's own constraints would refuse, and say so.

    A constraint violation aborts this funder's whole promotion: funders.cin is UNIQUE and
    funders_grant_band orders the band. A CIN already stored on this row is not overwritten.
    """
    update: dict[str, Any] = {}
    stored = None
    if match.entity_id is not None:
        stored = await (
            await conn.execute(
                "SELECT cin, grant_size_min, grant_size_max FROM funders WHERE id = %s",
                (match.entity_id,),
            )
        ).fetchone()
    if record.cin:
        holder = await cin_holder(conn, record.cin)
        if _is_foundation(record.name):
            report["held"].append(
                f"CIN {record.cin} is not written on {record.name!r}: a CIN names a company, and a "
                f"foundation's research usually carries its parent's. Link the parent by parent_id."
            )
            update["cin"] = None
        elif holder is not None and holder["id"] != match.entity_id:
            report["held"].append(
                f"CIN {record.cin} is already recorded on {holder['name']!r} [funder:{holder['id']}], "
                f"so it is not written on {record.name!r}. One CIN is one company."
            )
            update["cin"] = None
        elif stored and stored["cin"] and stored["cin"] != record.cin:
            report["held"].append(
                f"CIN {record.cin} differs from {stored['cin']} already stored on "
                f"{record.name!r}. Not written — a person decides which is current."
            )
            update["cin"] = None
    one_sided = (record.grant_size_min is None) != (record.grant_size_max is None)
    if stored and one_sided:
        lo = record.grant_size_min if record.grant_size_min is not None else stored["grant_size_min"]
        hi = record.grant_size_max if record.grant_size_max is not None else stored["grant_size_max"]
        if lo is not None and hi is not None and float(hi) < float(lo):
            report["held"].append(
                f"grant band for {record.name!r}: the research inverts the stored band "
                f"({stored['grant_size_min']} to {stored['grant_size_max']}). Not written — a "
                f"person decides which is current."
            )
            update.update(grant_size_min=None, grant_size_max=None)
    return record.model_copy(update=update) if update else record


def _answered(asking: Gate | None, table: str, name: str, match: Match, report: dict[str, Any]) -> Match | None:
    """A name that only resembles a stored one is merged or kept apart on a person's answer; None holds it."""
    top = match.candidates[0]
    choice = asking.on_entity(table, name, top) if asking else "ask"
    if choice == "update":
        return Match("alias", top["id"], top["score"])
    if choice == "new":
        return Match("none")
    names = ", ".join(c["name"] for c in match.candidates)
    report["reasons"].append(f"{name!r} resembles {names} without matching. Not merged — a person decides.")
    return None


async def link_partner_lines(conn: Any, org_id: int) -> int:
    """Funder partner lines that name this NGO but were written before Sangam held it, linked now. No model:
    the line's name, or a variant of it, must be the NGO's name or one of its aliases."""
    org = await (await conn.execute("SELECT name, aliases FROM orgs WHERE id = %s", (org_id,))).fetchone()
    if org is None:
        return 0
    keys = {name_key(n) for n in (org["name"], *(org["aliases"] or []))}
    rows = await (await conn.execute(
        "SELECT id, partner_name, partner_canonical FROM funder_activity "
        "WHERE kind = 'partner' AND partner_org_id IS NULL"
    )).fetchall()
    ids = [r["id"] for r in rows
           if keys & {name_key(n) for raw in (r["partner_name"], r["partner_canonical"]) if raw
                      for n in (raw, *variants(raw))}]
    if ids:
        await conn.execute("UPDATE funder_activity SET partner_org_id = %s WHERE id = ANY(%s)", (org_id, ids))
    return len(ids)


async def _resolved(conn: Any, row: dict[str, Any]) -> Match | None:
    """The entity an earlier save of this slug wrote to, while it still exists: a re-run never matches again.
    An "alias" match, because a person or the matcher already settled that this spelling is that entity."""
    column, table = (("resolved_org_id", "orgs") if row.get("entity_kind") == "org"
                     else ("resolved_funder_id", "funders"))
    found = await (await conn.execute(
        f"SELECT r.{column} AS id FROM entity_research r JOIN {table} t ON t.id = r.{column} "
        "WHERE r.slug = %s ORDER BY r.researched_at DESC LIMIT 1", (row["slug"],),
    )).fetchone()
    return Match("alias", found["id"]) if found else None


async def org_match(conn: Any, row: dict[str, Any], asking: Gate | None = None) -> Match | None:
    """The NGO a save of this research would write to, after any answer to "the same organisation?"; None waits."""
    findings = row["findings"] if isinstance(row.get("findings"), list) else []
    record = org_from(row, findings)
    name = record.name if record else row.get("canonical_name") or row.get("entity_name") or row["slug"]
    match = await _resolved(conn, row) or await resolve_org(
        conn, name, record.identifiers if record else None, record.website if record else None)
    return _answered(asking, "orgs", name, match, {"reasons": []}) if match.method == "trigram" else match


async def _promote_funder(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any],
    asking: Gate | None = None,
) -> None:
    record = funder_from(row, findings)
    if record is None:
        report["reasons"].append("no identity finding to build a funder from")
        return

    match = await _resolved(conn, row) or await resolve_funder(conn, record.name, record.cin, record.website)
    if match.method == "trigram":
        match = _answered(asking, "funders", record.name, match, report)
        if match is None:
            return
    if match.resolved:  # the same funder: every spelling the research used becomes an alias
        record = record.model_copy(update={"aliases": [*record.aliases, record.name]})
    record = await _reconcile_with_stored(conn, record, match, report)
    parent_id = await _parent(conn, record, report)
    status, funder_id, _ = await write_funder(conn, record, match, parent_id=parent_id)
    report["entity"] = {
        "kind": "funder", "status": status, "id": funder_id, "name": record.name
    }
    _settle_identity(report, findings, "identity", status, f"[funder:{funder_id}]")
    await _write_tags(conn, "funder_id", funder_id, record, record.name, report)

    owner = Owner.funder(funder_id)
    gate = GATE.get()
    # A plan writes nothing, and archiving moves storage objects, which no rollback undoes.
    docs = {} if gate and gate.plan else await _write_documents(conn, row, findings, owner, report)
    if gate and gate.plan:
        for f in findings:
            if f["concept"] == "document":
                _settle(report, f, {"state": "written"})
    years = {f["fiscal_year"]: f for f in findings if f["concept"] == "csr_year"}
    for year_record in csr_years_from(row, findings):
        state, _ = await write_csr_year(
            conn, year_record, funder_id, docs.get(year_record.source_url)
        )
        report["csr_years"].append({"fiscal_year": year_record.fiscal_year, "status": state})
        if year_record.fiscal_year in years and state in STATES:
            _settle(report, years[year_record.fiscal_year], {"state": STATES[state]})
    programs = await _write_programs(conn, row, findings, owner, docs, report)
    findings = [*findings, *_legacy_grants(findings, report)]
    await _write_facts(conn, row, findings, owner, programs, docs, report)
    if not (gate and gate.plan):
        await _link_research(conn, row, funder_id=funder_id)


async def _promote_org(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any],
    asking: Gate | None = None,
) -> None:
    """The NGO path. Same shape as the funder one bar two differences: there is
    no parent link to resolve, and write_org ranks by evidence tier."""
    record = org_from(row, findings)
    if record is None:
        report["reasons"].append(
            "no org_identity or org_identifier finding with a source_type and evidence_tier to build an "
            "organisation from (research saved before evidence tiers is re-researched, not promoted)"
        )
        return

    match = await _resolved(conn, row) or await resolve_org(
        conn, record.name, record.identifiers, record.website)
    if match.method == "trigram":
        match = _answered(asking, "orgs", record.name, match, report)
        if match is None:
            return
    record = await _reconcile_org_aliases(conn, record, match, report)
    parent_id = await _org_parent(conn, record, match, report)
    status, org_id, _, conflicts = await write_org(conn, record, match, parent_id=parent_id)
    report["entity"] = {"kind": "org", "status": status, "id": org_id, "name": record.name}
    _settle_identity(report, findings, "org_identity", status, f"[org:{org_id}]")
    if linked := await link_partner_lines(conn, org_id):
        report["written"].setdefault("funder_activity (partner link)", collections.Counter())["updated"] += linked
    await _write_tags(conn, "org_id", org_id, record, record.name, report)
    report["conflicts"].extend(c.describe() for c in conflicts)

    owner = Owner.org(org_id)
    docs = await _write_documents(conn, row, findings, owner, report)
    programs = await _write_programs(conn, row, findings, owner, docs, report)
    await _write_facts(
        conn, row, findings, owner, programs, docs, report, order=ORG_WRITE_ORDER
    )
    await _link_research(conn, row, org_id=org_id)


async def promote(conn: Any, row: dict[str, Any], *, gate: Gate | None = None) -> dict[str, Any]:
    """Write what can be written from one research row. Returns a report.

    With a gate, a funder's facts follow the five cases (writer.Gate); an NGO keeps fill-blanks and
    asks only whether a name that resembles a stored NGO's is the same organisation.
    """
    asking = gate
    if row.get("entity_kind") == "org":
        gate = None
    token = GATE.set(gate)
    try:
        report = await _promote(conn, row, asking)
    finally:
        GATE.reset(token)
    if asking and not gate:
        report["questions"] = asking.asked()
        report["held"].extend(
            f"{i['new_name']!r}: waiting for a person to say whether it is {i['stored_name']!r}"
            for i in report["questions"]
        )
    if gate:
        report["questions"] = gate.asked()
        report["changes"] = [i for i in gate.items if i["case"] in (2, 3, 4)
                             and i.get("outcome") in ("written", "planned")]
        report["plan"] = {"same": gate.same, "items": gate.items}
        report["held"].extend(
            f"{i['table']} {i['label']}: waiting for a person ({' / '.join(i['choices'])})"
            for i in report["questions"]
        )
        report["held"].extend(
            f"{i['table']} {i['label']}: {i['reason']}" for i in gate.items if i.get("outcome") == "held"
        )
    return report


async def _promote(conn: Any, row: dict[str, Any], asking: Gate | None = None) -> dict[str, Any]:
    findings = row["findings"] if isinstance(row["findings"], list) else []
    report: dict[str, Any] = {
        "slug": row["slug"], "entity": None, "csr_years": [],
        "written": {}, "held": [], "conflicts": [], "skipped": {}, "reasons": [], "facts": {},
    }
    for concept in sorted({f["concept"] for f in findings}):
        if concept not in PROMOTABLE and concept not in FOLDED:
            report["skipped"][concept] = len([f for f in findings if f["concept"] == concept])

    # Before the kind branch, not after it. An org row researched under the old
    # shape used to be turned away for having no writer, which is a reason that
    # has stopped existing; "re-run the research" is the one that says what to do.
    if findings and row.get("schema_version", 1) < TYPED_SINCE:
        report["reasons"].append(
            f"researched under finding shape v{row.get('schema_version', 1)}, which has no typed "
            f"fields to map. Re-run the research for {row['slug']} and promote that."
        )
        return report

    datasets = await _staff_dataset_rows(conn, findings)
    findings = _guarded(report, findings, staff_sources.hold_unmarked(
        findings, {u: d["id"] for u, d in datasets.items()}))
    # A marked staff figure is still held unless its cited row prints it, in the unit it was saved in.
    findings = _guarded(report, findings, await staff_sources.hold_mismatched(findings, datasets))
    # A vault finding was checked against its org's files at save; here only the funder's general facts pass.
    findings = _guarded(report, findings, vault.hold_at_promote(findings, row.get("entity_kind")))
    findings = _guarded(report, findings, source_guards.hold_at_promote(findings, row.get("entity_kind")))

    # An NGO is not a funder, and the two kinds reach different tables through
    # different resolvers. Nothing below this line is shared but the report.
    if row.get("entity_kind") == "org":
        await _promote_org(conn, row, findings, report, asking)
    else:
        await _promote_funder(conn, row, findings, report, asking)
    _unsettled(report, row["findings"] if isinstance(row["findings"], list) else [])
    report.pop("_raw", None)
    # Ten findings citing the same unresolvable state is one problem, not ten.
    report["held"] = list(dict.fromkeys(report["held"]))
    report["conflicts"] = list(dict.fromkeys(report["conflicts"]))
    return report


def now() -> datetime:
    return datetime.now(UTC)
