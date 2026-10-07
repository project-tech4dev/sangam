"""One organisation against one funder. rules.py judges each check; scoring.py computes the verdict."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.agent.scoring import Gate, Result, evaluate

Outcome = Literal["met", "fail", "unknown"]
# Why a check came out as it did. met/fail rest on evidence; unknown says what was missing.
Basis = Literal["recorded", "on_file", "not_researched", "searched_not_found", "not_on_file"]
EVIDENCE: frozenset[str] = frozenset({"recorded", "on_file"})
# About the organisation alone: the same for every funder.
ReadinessCode = Literal[
    "reg_12a", "reg_80g", "csr_1", "darpan", "pan", "reg_no", "fcra",
    "audits_3y", "itr_7", "board", "team_cvs", "projects_3",
]
# Depend on the funder.
PairCode = Literal["area", "theme", "programme", "turnover", "funder_bar"]
# A code outside these splits a comparison table.
CheckCode = Literal[ReadinessCode, PairCode]
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
        # The supervisor must repeat a real marker, brackets included.
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


class FunderAssessment(BaseModel):
    """One organisation against one funder: its checks, then the computed verdict."""

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
        # A funder can record several bars; every other code is one row of a comparison table.
        codes = [c.code for c in self.checks if c.code != "funder_bar"]
        if dupes := sorted({c for c in codes if codes.count(c) > 1}):
            raise ValueError(f"{dupes}: returned twice; each check once")
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

    # Computed, so they are always arithmetic on the checks and never set by hand.
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

