"""The seven match-v1 criteria, judged in code from two profiles. Pure: no pool, no async, no settings.

repositories/matching.py fills the profiles; rubric.py turns the points into a score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from app.agent import rubric
from app.agent.assessment import Criterion

# Spellings seen in the data. A new one is a one-line change here, not a rule change.
AUDIT_DOC_TYPES = frozenset({"audited_financials", "audit_report", "financial_statement", "financial_statements"})
# org_identifiers.status
HELD = frozenset({"registered", "provisional"})
LAPSED = frozenset({"cancelled", "expired", "suspended", "surrendered"})
INDIA = "India"
# CSR money routed through a company's foundation still needs a CSR-1 registered implementer.
SECTION_135_TYPES = frozenset({"corporate_csr", "corporate_foundation"})
UNTYPED = frozenset({None, "", "other"})
# eligibility item -> (label, what would earn it)
ITEMS = {
    "12a": ("12A", "Record the 12A registration"),
    "80g": ("80G", "Record the 80G registration"),
    "csr1": ("CSR Form 1", "Register CSR Form 1 with the MCA and record it"),
    "audits": ("Audited accounts", "Upload three years of audited accounts"),
}


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
    tags: frozenset[str]  # sector slugs, csr slugs, and the csr slugs the sector tags map to


@dataclass(frozen=True)
class Identifier:
    status: str
    id_value: str | None
    is_current: bool | None
    valid_until: date | None
    evidence: str | None
    source_type: str | None


@dataclass(frozen=True)
class PartnerLine:
    """A funder_activity line naming the organisation as its partner."""

    id: int
    funder_id: int
    relationship_status: str | None


@dataclass
class OrgProfile:
    id: int
    name: str
    location_ids: set[int] = field(default_factory=set)
    sector_tags: set[str] = field(default_factory=set)
    csr_slugs: set[str] = field(default_factory=set)
    population: set[str] = field(default_factory=set)  # its own and its programmes' population tags
    programs: list[Program] = field(default_factory=list)
    # id_type -> its org_identifiers rows
    identifiers: dict[str, list[Identifier]] = field(default_factory=dict)
    # (fiscal_year, is_audited), newest first
    financials: list[tuple[str, bool | None]] = field(default_factory=list)
    total_income: Decimal | None = None  # the latest year that records one, INR
    doc_types: list[str] = field(default_factory=list)
    partner_lines: list[PartnerLine] = field(default_factory=list)


@dataclass
class FunderProfile:
    id: int
    name: str
    funder_type: str | None
    section_135_bound: bool | None
    grant_size_min: Decimal | None = None
    grant_size_max: Decimal | None = None
    location_ids: set[int] = field(default_factory=set)
    registered_ids: set[int] = field(default_factory=set)
    sector_tags: set[str] = field(default_factory=set)
    csr_slugs: set[str] = field(default_factory=set)
    population: set[str] = field(default_factory=set)
    # (activity id, fiscal_year) of its spend and programme lines that carry an amount
    spend: list[tuple[int, str]] = field(default_factory=list)
    # (documents id, criterion) from the funder's 'funder_eligibility' document
    bars: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Finding:
    """A criterion plus what the write-up needs: the card line, actions and what was left out."""

    criterion: Criterion
    line: str
    improve: list[str] = field(default_factory=list)
    not_judged: list[str] = field(default_factory=list)


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


def _words(slugs: set[str]) -> str:
    return ", ".join(sorted(s.replace("_", " ") for s in slugs))


def _found(code: str, points: int | None, note: str, cites: list[str], line: str = "", **extra) -> Finding:
    return Finding(Criterion(code=code, points=points, note=note, cites=cites), line or note, **extra)


def _side(org_has: bool) -> str:
    return "funder" if org_has else "organisation"


# ---- theme, geography, population: what the two have in common ----------------------------------------


def theme(org: OrgProfile, funder: FunderProfile) -> Finding:
    shared = (org.sector_tags & funder.sector_tags) | (org.csr_slugs & funder.csr_slugs)
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    if shared:
        what = _words(shared)
        if hits := [p for p in org.programs if p.tags & shared]:
            return _found("theme", rubric.maximum("theme"), f"shared: {what}; {hits[0].name} is in it", cites,
                          f"Shared theme: {what}")
        if org.programs and all(p.tags for p in org.programs):
            why, act = f"none of {len(org.programs)} programmes is in it", f"Record a programme in {what}"
        elif org.programs:
            why, act = "its programmes are not tagged with a theme", "Tag the organisation's programmes with themes"
        else:
            why, act = "no programmes recorded", f"Record the organisation's programmes in {what}"
        gain = rubric.maximum("theme") - rubric.THEME_NO_PROGRAMME
        return _found("theme", rubric.THEME_NO_PROGRAMME, f"shared: {what}; {why}", cites,
                      f"No programme recorded in {what}", improve=[f"{act} (up to {gain} points)."])
    org_tagged, funder_tagged = bool(org.sector_tags or org.csr_slugs), bool(funder.sector_tags or funder.csr_slugs)
    if org_tagged and funder_tagged:
        return _found("theme", 0, "no shared sector or Schedule VII theme", cites, "No shared theme recorded")
    return _found("theme", None, f"no themes recorded for the {_side(org_tagged)}", [])


def geography(org: OrgProfile, funder: FunderProfile, places: Places) -> Finding:
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    pts = rubric.GEOGRAPHY
    if shared := places.districts(org.location_ids) & places.districts(funder.location_ids):
        return _found("geography", pts["district"], f"shared district: {_names(places, shared)}", cites,
                      f"Both work in {_names(places, shared)}")
    if shared := places.states(org.location_ids) & places.states(funder.location_ids):
        return _found("geography", pts["state"], f"shared state, no shared district: {_names(places, shared)}",
                      cites, f"{_names(places, shared)} is one of its states")
    if places.pan_india(funder.location_ids) and org.location_ids:
        return _found("geography", pts["india"], "the funder gives across India; no state or district named",
                      cites, "Gives across India")
    regions = places.regions(funder.location_ids)
    for r in regions:
        if inside := places.members(r) & places.states(org.location_ids):
            return _found("geography", pts["region"], f"region {places.name(r)} includes {_names(places, inside)}",
                          cites, f"Gives in {places.name(r)}")
    if not org.location_ids or not funder.location_ids:
        return _found("geography", None, f"no places recorded for the {_side(bool(org.location_ids))}", [])
    if any(not places.members(r) for r in regions):
        # A region whose member states are not recorded can neither match nor rule out.
        return _found("geography", None,
                      f"the funder gives in {_names(places, regions)}; its member states are not recorded", [])
    return _found("geography", 0, f"no shared place among {len(funder.location_ids)} recorded funder places",
                  cites, "No shared place recorded")


def population(org: OrgProfile, funder: FunderProfile) -> Finding:
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    if shared := org.population & funder.population:
        return _found("population", rubric.maximum("population"), f"both serve {_words(shared)}", cites,
                      f"Both serve {_words(shared)}")
    if org.population and funder.population:
        return _found("population", 0, f"{_words(org.population)} against {_words(funder.population)}", cites,
                      "Serves a different population")
    return _found("population", None, f"no population recorded for the {_side(bool(org.population))}", [])


# ---- eligibility: the organisation's papers against what this funder needs ------------------------------


def _credential(key: str, org: OrgProfile, today: date) -> tuple[str, str]:
    """(held | missing | unreadable, note) for one org_identifiers id_type."""
    rows = [r for r in org.identifiers.get(key, []) if r.is_current is not False]
    lapsed = [r for r in rows if r.status in LAPSED or (r.status in HELD and r.valid_until and r.valid_until < today)]
    held = [r for r in rows if r.status in HELD and r.id_value and r not in lapsed]
    label = ITEMS[key][0]
    if held and lapsed:
        return "unreadable", f"{label}: conflicting rows ({', '.join(sorted({r.status for r in rows}))})"
    if lapsed:
        r = lapsed[0]
        return "missing", (f"{label} lapsed on {r.valid_until}" if r.status in HELD else f"{label} {r.status}")
    if held:
        r = held[0]
        if r.evidence == "claimed":
            return "held", f"{label} claimed by {r.source_type or 'an unnamed source'}, not evidenced"
        return "held", f"{label} {r.status}" + (" (time-limited)" if r.status == "provisional" else "")
    statuses = {r.status for r in rows}
    if "check_blocked" in statuses:
        return "unreadable", f"{label}: the registry could not be read"
    if "applied" in statuses:
        return "missing", f"{label} applied for, not yet granted"
    if "not_found" in statuses:
        return "missing", f"{label} searched for and not found"
    return "missing", f"{label} not on record"


def _audits(org: OrgProfile) -> tuple[str, str]:
    audited = {y for y, a in org.financials if a is True}
    docs = sum(t in AUDIT_DOC_TYPES for t in org.doc_types)
    if len(audited) >= 3:
        return "held", f"{len(audited)} audited years"
    if docs >= 3:
        return "held", f"{docs} audit documents on file"
    return "missing", f"{max(len(audited), docs)} of 3 audited years on record"


def eligibility(org: OrgProfile, funder: FunderProfile, *, today: date) -> Finding:
    cites = [f"[org:{org.id}]"]
    not_judged = [f"The funder's own bar (document {doc_id}) [funder:{funder.id}]: {text}"
                  for doc_id, text in funder.bars]
    if not (org.identifiers or org.financials or org.doc_types):
        return _found("eligibility", None, "no registrations, accounts or documents recorded", [],
                      not_judged=not_judged)
    items = {"12a": _credential("12a", org, today), "80g": _credential("80g", org, today), "audits": _audits(org)}
    if funder.funder_type in SECTION_135_TYPES or funder.section_135_bound:
        items["csr1"] = _credential("csr1", org, today)
    elif funder.funder_type in UNTYPED and funder.section_135_bound is None:
        not_judged.append("CSR Form 1: the funder's type is not recorded, so whether Section 135 applies is unknown.")
    # An unreadable item is left out of the count, never scored as missing.
    not_judged += [f"{note}." for state, note in items.values() if state == "unreadable"]
    counted = {k: v for k, v in items.items() if v[0] != "unreadable"}
    if not counted:
        return _found("eligibility", None, "no credential could be read", [], not_judged=not_judged)
    held = [note for state, note in counted.values() if state == "held"]
    missing = {k: note for k, (state, note) in counted.items() if state == "missing"}
    points = round(rubric.maximum("eligibility") * len(held) / len(counted))
    share = round(rubric.maximum("eligibility") / len(counted))
    note = "; ".join([*held, *missing.values()])
    line = next(iter(missing.values()), "12A, 80G and audited accounts on record")
    improve = [f"{ITEMS[k][1]} (up to {share} points)." for k in missing]
    return _found("eligibility", points, note, cites, line, improve=improve, not_judged=not_judged)


# ---- relationship, funding size, capacity: about this funder -------------------------------------------


def relationship(org: OrgProfile, funder: FunderProfile) -> Finding:
    lines = [p for p in org.partner_lines if p.funder_id == funder.id]
    confirmed = [p for p in lines if p.relationship_status != "unconfirmed"]
    if confirmed:
        statuses = ", ".join(sorted({p.relationship_status or "unstated" for p in confirmed}))
        return _found("relationship", rubric.maximum("relationship"),
                      f"{len(confirmed)} partner line(s) from this funder ({statuses})",
                      [f"[activity:{p.id}]" for p in confirmed], "Has funded it before")
    if lines:
        gain = rubric.maximum("relationship") - rubric.RELATIONSHIP_UNCONFIRMED
        return _found("relationship", rubric.RELATIONSHIP_UNCONFIRMED, "a partner line exists but is unconfirmed",
                      [f"[activity:{p.id}]" for p in lines], "A past grant is unconfirmed",
                      improve=[f"Confirm the partner line with {funder.name} (up to {gain} points)."])
    return _found("relationship", 0, "no past grant, programme or contact between them is recorded", [],
                  "No past grant or contact recorded",
                  improve=[(f"Record any contact with {funder.name}; a warm introduction counts "
                            f"(up to {rubric.maximum('relationship')} points).")])


def _inr(amount: Decimal) -> str:
    return f"₹{amount / 100_000:,.1f} lakh" if amount < 10_000_000 else f"₹{amount / 10_000_000:,.1f} crore"


def funding_size(org: OrgProfile, funder: FunderProfile) -> Finding:
    if funder.grant_size_min is None and funder.grant_size_max is None:
        return _found("funding_size", None, "the funder publishes no grant range", [])
    if org.total_income is None:
        return _found("funding_size", None, "no annual income recorded for the organisation", [])
    cites = [f"[org:{org.id}]", f"[funder:{funder.id}]"]
    smallest = funder.grant_size_min or Decimal(0)
    band = " to ".join(_inr(a) for a in (funder.grant_size_min, funder.grant_size_max) if a is not None)
    note = f"grants of {band} against an annual income of {_inr(org.total_income)}"
    if smallest <= org.total_income:
        return _found("funding_size", rubric.maximum("funding_size"), note, cites, f"Grant size fits: {band}")
    if smallest <= rubric.FUNDING_STRETCH * org.total_income:
        return _found("funding_size", rubric.FUNDING_PARTIAL, note, cites, "Its smallest grant is a stretch")
    return _found("funding_size", 0, note, cites, "Its smallest grant is far above the organisation's income")


def _fy(start: int) -> str:
    return f"FY{start}-{(start + 1) % 100:02d}"


def capacity(funder: FunderProfile, *, today: date) -> Finding:
    window = rubric.capacity_window(today)
    recent = [(a, fy) for a, fy in funder.spend if rubric.fy_start(fy) in window]
    years = {rubric.fy_start(fy) for _, fy in recent}
    span = f"{_fy(window[0])} to {_fy(window[-1])}"
    if not years:
        return _found("capacity", None, f"no spend recorded from {span}", [])
    cites = list(dict.fromkeys(f"[activity:{a}]" for a, _ in recent))[:3]
    note = f"spend recorded in {len(years)} of the {rubric.CAPACITY_YEARS} years {span}"
    if len(years) >= rubric.CAPACITY_YEARS:
        return _found("capacity", rubric.maximum("capacity"), note, cites, "Spends every year")
    return _found("capacity", rubric.CAPACITY_PARTIAL, note, cites, "Spend recorded in some recent years")


def judge(org: OrgProfile, funder: FunderProfile, places: Places, *, today: date | None = None) -> list[Finding]:
    """Every criterion, in the rubric's order."""
    today = today or datetime.now(UTC).date()
    return [
        theme(org, funder),
        geography(org, funder, places),
        population(org, funder),
        eligibility(org, funder, today=today),
        relationship(org, funder),
        funding_size(org, funder),
        capacity(funder, today=today),
    ]


def has_places_or_themes(funder: FunderProfile) -> bool:
    return bool(funder.location_ids or funder.sector_tags or funder.csr_slugs)
