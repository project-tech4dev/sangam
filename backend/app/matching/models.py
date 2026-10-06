"""What the engine returns. Domain objects only — the tool layer renders them to text."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["met", "fail", "unknown"]
Basis = Literal[
    "recorded", "on_file", "not_researched", "searched_not_found", "not_on_file", "not_applicable"
]
Role = Literal["gate", "weighted", "advisory", "none"]
GateStatus = Literal["passed", "unverified", "failed"]


class OrgRef(BaseModel):
    id: int
    name: str
    slug: str | None = None


class FunderRef(BaseModel):
    id: int
    name: str
    slug: str | None = None
    funder_type: str | None = None


class CheckResult(BaseModel):
    code: str
    label: str
    group: str | None = None
    category: str | None = None
    role: Role
    weight: int = 0
    outcome: Outcome
    basis: Basis
    level: str | None = None
    reason_code: str
    reason_params: dict = Field(default_factory=dict)
    cites: list[str] = Field(default_factory=list)


class CategoryScore(BaseModel):
    earned: float
    unknown: float
    applicable: int


class Assessment(BaseModel):
    criteria_version: int
    criteria_hash: str
    org: OrgRef
    funder: FunderRef
    gate_status: GateStatus
    fit_status: Outcome
    failed_gates: list[str] = Field(default_factory=list)
    checks: list[CheckResult]
    score_min: int
    score_max: int
    coverage: int
    breakdown: dict[str, CategoryScore]
    shared_districts: int = 0
    gaps: list[CheckResult] = Field(default_factory=list)
    advisory_gaps: list[CheckResult] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class Shortlist(BaseModel):
    criteria_version: int
    criteria_hash: str
    org: OrgRef
    ranked: list[Assessment]
    not_enough_recorded: list[FunderRef]
    did_not_pass: list[Assessment]
    total_funders: int
    offset: int
    limit: int


class Resolved(BaseModel):
    kind: Literal["org", "funder"]
    id: int
    name: str
    slug: str | None = None


class Ambiguous(BaseModel):
    """Text that named no single org or funder; the caller asks which one was meant."""

    kind: Literal["org", "funder"]
    text: str
    candidates: list[Resolved]


# --- profiles and stated-profile search (M3) --------------------------------------------------

class Place(BaseModel):
    name: str
    kind: str
    role: str | None = None


class Theme(BaseModel):
    slug: str
    label: str
    inferred: bool


class Programme(BaseModel):
    id: int
    name: str
    kind: str | None = None
    clauses: list[str] = Field(default_factory=list)


class Requirement(BaseModel):
    kind: str
    criterion: str


class CsrYear(BaseModel):
    fiscal_year: str
    prescribed_csr: int | None = None
    total_spent: int | None = None


class Partner(BaseModel):
    name: str
    kind: str | None = None
    org_id: int | None = None


class Call(BaseModel):
    id: int
    title: str
    deadline: str | None = None
    deadline_passed: bool = False
    amount_min: int | None = None
    amount_max: int | None = None
    url: str | None = None


class FunderProfile(BaseModel):
    """Everything recorded about one funder; an empty list means not recorded."""

    funder: FunderRef
    website: str | None = None
    section_135_bound: bool | None = None
    places: list[Place] = Field(default_factory=list)
    registered: list[Place] = Field(default_factory=list)
    footprint_places: int = 0
    footprint_latest_year: str | None = None
    themes: list[Theme] = Field(default_factory=list)
    programmes: list[Programme] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    csr_years: list[CsrYear] = Field(default_factory=list)
    spend_rows: int = 0
    spend_by_state: list[tuple[str, int]] = Field(default_factory=list)
    spend_by_sector: list[tuple[str, int]] = Field(default_factory=list)
    partner_kinds: dict[str, int] = Field(default_factory=dict)
    partners: list[Partner] = Field(default_factory=list)
    calls: list[Call] = Field(default_factory=list)


class Dimension(BaseModel):
    outcome: Outcome
    basis: Basis
    reason_code: str
    reason_params: dict = Field(default_factory=dict)
    level: str | None = None


class FunderMatch(BaseModel):
    funder: FunderRef
    outcome: Outcome
    dims: dict[str, Dimension]


class FunderList(BaseModel):
    """Funders against a stated place, theme or type: matches, not recorded, and a count of the rest."""

    places: list[str]
    themes: list[str]
    funder_types: list[str]
    matched: list[FunderMatch]
    matched_total: int
    not_recorded: list[FunderMatch]
    no_overlap: int
    total_funders: int
    offset: int
    limit: int
