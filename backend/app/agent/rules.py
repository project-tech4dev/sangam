"""Funder matching checks, judged in code from two profiles. Pure: no pool, no async, no settings.

repositories/matching.py fills the profiles; scoring.py turns these checks into a gate and a score.
A missing row is never `fail`: only a recorded fact can fail a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.agent.assessment import Check

# Spellings seen in the data. A new one is a one-line change here, not a rule change.
AUDIT_DOC_TYPES = frozenset({"audited_financials", "audit_report", "financial_statement", "financial_statements"})
ITR_DOC_TYPES = frozenset({"itr", "itr_7", "itr7", "income_tax_return"})
CV_DOC_TYPES = frozenset({"cv", "cvs", "team_cv", "team_cvs", "resume"})
CONCLUDED = frozenset({"concluded", "completed", "closed", "ended"})
# check code -> org_identifiers.id_type
CREDENTIALS = {
    "reg_12a": "12a", "reg_80g": "80g", "csr_1": "csr1", "darpan": "darpan",
    "pan": "pan", "reg_no": "reg_no", "fcra": "fcra",
}
# org_identifiers.status
HELD = frozenset({"registered", "provisional"})
LAPSED = frozenset({"cancelled", "expired", "suspended", "surrendered"})
INDIA = "India"


@dataclass(frozen=True)
class Location:
    id: int
    kind: str
    name: str
    parent_id: int | None


@dataclass(frozen=True)
class Program:
    id: int
    name: str
    status: str | None
    end_date: date | None
    tags: frozenset[str]  # sector slugs, csr slugs, and the csr slugs the sector tags map to


@dataclass(frozen=True)
class Identifier:
    status: str
    id_value: str | None
    is_current: bool | None
    valid_until: date | None
    evidence: str | None
    source_type: str | None


@dataclass
class OrgProfile:
    id: int
    name: str
    location_ids: set[int] = field(default_factory=set)
    sector_tags: set[str] = field(default_factory=set)
    csr_slugs: set[str] = field(default_factory=set)
    programs: list[Program] = field(default_factory=list)
    # id_type -> its org_identifiers rows
    identifiers: dict[str, list[Identifier]] = field(default_factory=dict)
    # (fiscal_year, is_audited), newest first
    financials: list[tuple[str, bool | None]] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    office_bearers: int = 0
    # funder_activity partner lines naming the org: (activity id, relationship_status, end_date)
    partner_lines: list[tuple[int, str | None, date | None]] = field(default_factory=list)


@dataclass
class FunderProfile:
    id: int
    name: str
    funder_type: str | None
    section_135_bound: bool | None
    location_ids: set[int] = field(default_factory=set)
    registered_ids: set[int] = field(default_factory=set)
    sector_tags: set[str] = field(default_factory=set)
    csr_slugs: set[str] = field(default_factory=set)
    # (documents id, criterion) from the funder's 'funder_eligibility' document
    bars: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PairResult:
    checks: list[Check]
    shared_districts: int
    foreign_funder: bool | None
    reasons: list[str]


class Places:
    """The locations table, small enough to walk in memory."""

    def __init__(self, rows: list[Location]):
        self.by_id = {r.id: r for r in rows}

    def kind(self, loc_id: int) -> str | None:
        loc = self.by_id.get(loc_id)
        return loc.kind if loc else None

    def name(self, loc_id: int) -> str:
        loc = self.by_id.get(loc_id)
        return loc.name if loc else str(loc_id)

    def districts(self, ids: set[int]) -> set[int]:
        return {i for i in ids if self.kind(i) == "district"}

    def states(self, ids: set[int]) -> set[int]:
        # A district's state is its parent; never take a state's parent, which is the country.
        found = {i for i in ids if self.kind(i) == "state"}
        for i in self.districts(ids):
            parent = self.by_id[i].parent_id
            if parent is not None and self.kind(parent) == "state":
                found.add(parent)
        return found

    def regions(self, ids: set[int]) -> set[int]:
        return {i for i in ids if self.kind(i) == "region"}

    def members(self, region_id: int) -> set[int]:
        return {loc.id for loc in self.by_id.values() if loc.parent_id == region_id and loc.kind == "state"}

    def pan_india(self, ids: set[int]) -> bool:
        return any(self.kind(i) == "country" and self.name(i) == INDIA for i in ids)

    def country(self, loc_id: int) -> str | None:
        seen: set[int] = set()
        cur = self.by_id.get(loc_id)
        while cur is not None and cur.id not in seen:
            if cur.kind == "country":
                return cur.name
            seen.add(cur.id)
            cur = self.by_id.get(cur.parent_id) if cur.parent_id is not None else None
        return None


def _names(places: Places, ids: set[int]) -> str:
    return ", ".join(sorted(places.name(i) for i in ids))


def _unknown(code: str, note: str = "", basis: str = "not_researched") -> Check:
    return Check(code=code, outcome="unknown", basis=basis, note=note)


# ---- organisation's own checks: the same for every funder ----------------------------------------------


def _credential(code: str, org: OrgProfile, today: date) -> Check:
    key = CREDENTIALS[code]
    cite = [f"[org:{org.id}]"]
    rows = [r for r in org.identifiers.get(key, []) if r.is_current is not False]
    lapsed = [r for r in rows if r.status in LAPSED or (r.status in HELD and r.valid_until and r.valid_until < today)]
    held = [r for r in rows if r.status in HELD and r.id_value and r not in lapsed]
    if held and lapsed:
        # Conflicting evidence never passes or fails a gate.
        return _unknown(code, f"conflicting {key} rows: {', '.join(sorted({r.status for r in rows}))}")
    if lapsed:
        r = lapsed[0]
        note = f"{key} lapsed on {r.valid_until}" if r.status in HELD else f"{key} {r.status}"
        return Check(code=code, outcome="fail", basis="recorded", note=note, cites=cite)
    if held:
        r = held[0]
        if r.evidence == "claimed":
            # Weak evidence never passes a gate.
            return _unknown(code, f"{key} claimed by {r.source_type or 'an unnamed source'}, not evidenced",
                            basis="claimed")
        note = f"{key} {r.status}" + (" (time-limited)" if r.status == "provisional" else "")
        return Check(code=code, outcome="met", basis="recorded", note=note, cites=cite)
    statuses = {r.status for r in rows}
    if "applied" in statuses:
        return _unknown(code, f"{key} applied for, not yet granted")
    if "not_found" in statuses:
        return _unknown(code, f"{key} searched for and not found", basis="searched_not_found")
    if "check_blocked" in statuses:
        return _unknown(code, f"{key} registry could not be read")
    if org.identifiers.get(key):
        return _unknown(code, f"no current {key} recorded")
    return _unknown(code, f"no {key} recorded")


def _audits(org: OrgProfile) -> Check:
    cite = [f"[org:{org.id}]"]
    audited = {y for y, a in org.financials if a is True}
    docs = sum(t in AUDIT_DOC_TYPES for t in org.doc_types)
    if len(audited) >= 3:
        return Check(code="audits_3y", outcome="met", basis="recorded", note=f"{len(audited)} audited years", cites=cite)
    if docs >= 3:
        return Check(code="audits_3y", outcome="met", basis="on_file", note=f"{docs} audit documents", cites=cite)
    if unaudited := [y for y, a in org.financials[:3] if a is False]:
        return Check(code="audits_3y", outcome="fail", basis="recorded",
                     note=f"recorded not audited: {', '.join(unaudited)}", cites=cite)
    return _unknown("audits_3y", f"{max(len(audited), docs)} of 3 audited years recorded")


def _document(code: str, kinds: frozenset[str], what: str, org: OrgProfile) -> Check:
    if any(t in kinds for t in org.doc_types):
        return Check(code=code, outcome="met", basis="on_file", note=f"{what} on file", cites=[f"[org:{org.id}]"])
    return _unknown(code, f"no {what} on file", basis="not_on_file")


def _board(org: OrgProfile) -> Check:
    if org.office_bearers >= 3:
        return Check(code="board", outcome="met", basis="recorded",
                     note=f"{org.office_bearers} office bearers", cites=[f"[org:{org.id}]"])
    return _unknown("board", f"{org.office_bearers} of 3 office bearers recorded")


def _projects(org: OrgProfile, today: date) -> Check:
    # An unconfirmed line is a claim of a relationship, not a project.
    grants = [a for a, status, end in org.partner_lines
              if status != "unconfirmed" and (status in CONCLUDED or (end is not None and end < today))]
    programs = [p for p in org.programs if p.status in CONCLUDED or (p.end_date is not None and p.end_date < today)]
    done = len(grants) + len(programs)
    if done >= 3:
        cites = [f"[activity:{a}]" for a in grants] or [f"[org:{org.id}]"]
        return Check(code="projects_3", outcome="met", basis="recorded",
                     note=f"{len(grants)} concluded grants, {len(programs)} completed programmes", cites=cites)
    return _unknown("projects_3", f"{done} of 3 completed projects recorded")


def judge_org(org: OrgProfile, *, today: date | None = None) -> list[Check]:
    """The twelve checks about the organisation alone."""
    today = today or datetime.now(UTC).date()
    return [
        *(_credential(code, org, today) for code in CREDENTIALS),
        _audits(org),
        _document("itr_7", ITR_DOC_TYPES, "income tax return", org),
        _board(org),
        _document("team_cvs", CV_DOC_TYPES, "team CV", org),
        _projects(org, today),
    ]


# ---- checks that depend on the funder ------------------------------------------------------------------


def _area(org: OrgProfile, funder: FunderProfile, places: Places) -> tuple[Check, int]:
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    o_d, f_d = places.districts(org.location_ids), places.districts(funder.location_ids)
    o_s, f_s = places.states(org.location_ids), places.states(funder.location_ids)
    shared_d = o_d & f_d
    if shared_d:
        note = f"shared district: {_names(places, shared_d)}"
        return Check(code="area", outcome="met", basis="recorded", level="district", note=note, cites=cites), \
            len(shared_d)
    if shared_s := o_s & f_s:
        note = f"shared state: {_names(places, shared_s)}"
        return Check(code="area", outcome="met", basis="recorded", level="state", note=note, cites=cites), 0
    if places.pan_india(funder.location_ids):
        note = "funder states it gives across India"
        return Check(code="area", outcome="met", basis="recorded", level="pan_india", note=note, cites=cites), 0
    regions = places.regions(funder.location_ids)
    for r in regions:
        if places.members(r) & o_s:
            note = f"region {places.name(r)} includes {_names(places, places.members(r) & o_s)}"
            return Check(code="area", outcome="met", basis="recorded", level="regional", note=note, cites=cites), 0
    if not org.location_ids or not funder.location_ids:
        side = "organisation" if not org.location_ids else "funder"
        return _unknown("area", f"no places recorded for the {side}"), 0
    if any(not places.members(r) for r in regions):
        # A region whose member states are not recorded can neither match nor rule out.
        return _unknown("area", f"funder gives in {_names(places, regions)}; its member states are not recorded"), 0
    note = f"no shared place among {len(f_s | f_d)} recorded funder places"
    return Check(code="area", outcome="fail", basis="recorded", note=note, cites=cites), 0


def _theme(org: OrgProfile, funder: FunderProfile) -> tuple[Check, set[str]]:
    shared = (org.sector_tags & funder.sector_tags) | (org.csr_slugs & funder.csr_slugs)
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    if shared:
        return Check(code="theme", outcome="met", basis="recorded", note=f"shared: {', '.join(sorted(shared))}",
                     cites=cites), shared
    org_tagged = bool(org.sector_tags or org.csr_slugs)
    funder_tagged = bool(funder.sector_tags or funder.csr_slugs)
    if org_tagged and funder_tagged:
        return Check(code="theme", outcome="fail", basis="recorded", note="no shared sector or Schedule VII theme",
                     cites=cites), shared
    side = "organisation" if not org_tagged else "funder"
    return _unknown("theme", f"no themes recorded for the {side}"), shared


def _programme(org: OrgProfile, theme: Check, shared: set[str]) -> Check:
    # A fail needs a programs row to cite, so no programmes is unknown whatever theme says.
    if not org.programs:
        return _unknown("programme", "no programmes recorded for the organisation")
    if hits := [p for p in org.programs if p.tags & shared]:
        return Check(code="programme", outcome="met", basis="recorded",
                     note=f"{hits[0].name} is in a shared theme", cites=[f"[org:{org.id}]"])
    if theme.outcome == "fail" or (theme.outcome == "met" and all(p.tags for p in org.programs)):
        return Check(code="programme", outcome="fail", basis="recorded",
                     note=f"none of {len(org.programs)} programmes is in a shared theme", cites=[f"[org:{org.id}]"])
    return _unknown("programme", "programmes are not tagged with a theme")


def _foreign(funder: FunderProfile, places: Places) -> bool | None:
    countries = {places.country(i) for i in funder.registered_ids} - {None}
    if not countries:
        return None
    return INDIA not in countries


def judge_pair(org: OrgProfile, funder: FunderProfile, places: Places) -> PairResult:
    """Place, theme, programme and the funder's own bars."""
    area, shared_districts = _area(org, funder, places)
    theme, shared = _theme(org, funder)
    checks = [area, theme, _programme(org, theme, shared)]
    # Free-text criteria cannot be judged in code; each is named for a person to review.
    checks += [
        Check(code="funder_bar", outcome="unknown", basis="not_researched", note=f"needs review (document {bar_id}): {text}")
        for bar_id, text in funder.bars
    ]
    reasons = [f"{c.code}: {c.note} {' '.join(c.cites)}" for c in checks if c.outcome != "unknown"]
    return PairResult(checks, shared_districts, _foreign(funder, places), reasons)


def has_places_or_themes(funder: FunderProfile) -> bool:
    return bool(funder.location_ids or funder.sector_tags or funder.csr_slugs)
