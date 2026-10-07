"""What the matching subagents hand back. The models judge each check; scoring.py computes the verdict.

org-readiness judges the organisation's own checks once; funder-assessor judges the rest per funder;
merge() joins the two into a FunderAssessment.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.agent.scoring import Gate, Result, evaluate

Outcome = Literal["met", "fail", "unknown"]
# Why a check came out as it did. met/fail rest on evidence; unknown says what was missing.
Basis = Literal["recorded", "on_file", "not_researched", "searched_not_found", "not_on_file"]
EVIDENCE: frozenset[str] = frozenset({"recorded", "on_file"})
# About the organisation alone (prompts/org_readiness.md): the same for every funder.
ReadinessCode = Literal[
    "reg_12a", "reg_80g", "csr_1", "darpan", "pan", "reg_no", "fcra",
    "audits_3y", "itr_7", "board", "team_cvs", "projects_3",
]
# Depend on the funder (prompts/funder_assessor.md).
PairCode = Literal["area", "theme", "programme", "turnover", "funder_bar"]
# A code outside these splits a comparison table.
CheckCode = Literal[ReadinessCode, PairCode]
PAIR_REQUIRED = ("area", "theme", "programme")
# How close a shared place is; scoring.py grades the area points by it.
AreaLevel = Literal["district", "state", "pan_india", "regional"]


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CheckCode = Field(description="the checklist item, e.g. area, theme, reg_12a, audits_3y")
    outcome: Outcome
    basis: Basis
    level: AreaLevel | None = Field(
        default=None, description="area only, when met: the closest shared level, district > state > pan_india > regional"
    )
    note: str = Field(default="", description="one line: what was found, e.g. 'board of 2, needs 3'")
    cites: list[str] = Field(default_factory=list, description="markers of the rows used, e.g. [org:126]")

    @field_validator("cites")
    @classmethod
    def _bracketed(cls, cites: list[str]) -> list[str]:
        # The model sometimes drops the brackets; the supervisor must repeat a real marker.
        return [c if c.startswith("[") else f"[{c.strip()}]" for c in cites]

    @model_validator(mode="after")
    def _evidence_backs_a_verdict(self) -> Check:
        # Only positive evidence fails a check: absence is a fact about our research, not the NGO.
        if self.outcome == "unknown":
            if self.basis in EVIDENCE:
                raise ValueError(f"{self.code}: an unknown has no evidence, so its basis cannot be {self.basis}")
        elif self.basis not in EVIDENCE:
            raise ValueError(f"{self.code}: {self.basis} is missing evidence, so the outcome is unknown")
        elif not self.cites:
            raise ValueError(f"{self.code}: a {self.outcome} must cite the rows it rests on")
        if (self.code == "area" and self.outcome == "met") != (self.level is not None):
            raise ValueError(f"{self.code}: a level goes on a met area, and only there")
        return self


class ReadinessCheck(Check):
    code: ReadinessCode = Field(description="an organisation-only check, e.g. reg_12a, audits_3y, board")


class PairCheck(Check):
    code: PairCode = Field(description="a check that depends on the funder: area, theme, programme, turnover, funder_bar")


def _one_per_code(checks: Iterable[Check], required: Iterable[str]) -> None:
    # A funder can record several bars; every other code is one row of a comparison table.
    seen: set[str] = set()
    for c in checks:
        if c.code != "funder_bar" and c.code in seen:
            raise ValueError(f"{c.code}: returned twice; return each check once")
        seen.add(c.code)
    if missing := [code for code in required if code not in seen]:
        raise ValueError(f"missing checks {missing}: return every one, unknown when not recorded")


class ReadinessAssessment(BaseModel):
    """One organisation's own checks, judged once and reused for every funder."""

    model_config = ConfigDict(extra="forbid")

    org_id: int
    org_name: str
    checks: list[ReadinessCheck]
    gaps: list[str] = Field(default_factory=list, description="what to record or upload next, most important first")

    @model_validator(mode="after")
    def _complete(self) -> ReadinessAssessment:
        _one_per_code(self.checks, get_args(ReadinessCode))
        return self


class PairAssessment(BaseModel):
    """What depends on one funder, for an organisation whose readiness is already judged."""

    model_config = ConfigDict(extra="forbid")

    org_id: int
    funder_id: int
    funder_name: str
    funder_type: str | None = Field(description="funders.funder_type as recorded, or null")
    section_135_bound: bool | None = Field(description="funders.section_135_bound as recorded, or null")
    foreign_funder: bool | None = Field(description="true when the money is a foreign contribution; null if unknown")
    shared_districts: int = Field(default=0, ge=0, description="districts both sides have recorded")
    reasons: list[str] = Field(description="the facts that matter most, one line each, cited")
    checks: list[PairCheck]
    gaps: list[str] = Field(default_factory=list, description="what to record next for this funder, most important first")

    @model_validator(mode="after")
    def _complete(self) -> PairAssessment:
        _one_per_code(self.checks, PAIR_REQUIRED)
        return self


class FunderAssessment(BaseModel):
    """One organisation against one funder: readiness and pair checks joined, then scored."""

    model_config = ConfigDict(extra="forbid")

    org_id: int
    funder_id: int
    funder_name: str
    funder_type: str | None = Field(description="funders.funder_type as recorded, or null")
    section_135_bound: bool | None = Field(description="funders.section_135_bound as recorded, or null")
    foreign_funder: bool | None = Field(default=None, description="true when the money is a foreign contribution")
    shared_districts: int = Field(default=0, ge=0, description="districts both sides have recorded")
    reasons: list[str] = Field(description="the facts that matter most, one line each, cited")
    checks: list[Check]
    gaps: list[str] = Field(default_factory=list, description="what to record or upload next, most important first")

    @model_validator(mode="after")
    def _one_check_per_code(self) -> FunderAssessment:
        _one_per_code(self.checks, ())
        return self

    @property
    def _result(self) -> Result:
        return evaluate(
            ((c.code, c.outcome, c.level) for c in self.checks),
            funder_type=self.funder_type,
            section_135_bound=self.section_135_bound,
            foreign_funder=self.foreign_funder,
            shared_districts=self.shared_districts,
            funder_id=self.funder_id,
        )

    # Computed, so absent from the schema the model fills and present in the JSON the supervisor reads.
    @computed_field
    @property
    def gate(self) -> Gate:
        return self._result.gate

    @computed_field
    @property
    def gate_reasons(self) -> list[str]:
        return self._result.gate_reasons

    @computed_field
    @property
    def score(self) -> int:
        return self._result.score

    @computed_field
    @property
    def breakdown(self) -> dict[str, float]:
        return self._result.breakdown

    @computed_field
    @property
    def coverage(self) -> float:
        return self._result.coverage

    @computed_field
    @property
    def rank_key(self) -> str:
        return self._result.rank_key


def merge(readiness: dict, pair: PairAssessment) -> FunderAssessment:
    """Join the organisation's stored readiness with one funder's checks. Code, so nothing is re-typed."""
    stored = ReadinessAssessment.model_validate(readiness)
    if stored.org_id != pair.org_id:
        raise ValueError(f"readiness is for org {stored.org_id}, the funder check for org {pair.org_id}")
    gaps = list(dict.fromkeys([*pair.gaps, *stored.gaps]))
    return FunderAssessment(
        **pair.model_dump(exclude={"checks", "gaps"}),
        checks=[*pair.checks, *stored.checks],
        gaps=gaps,
    )
