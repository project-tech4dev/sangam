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
