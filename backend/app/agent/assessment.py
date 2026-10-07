"""What a funder-assessor hands back. The model judges; this only fixes the shape."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Outcome = Literal["met", "fail", "unknown"]
# Why a check came out as it did. met/fail rest on evidence; unknown says what was missing.
Basis = Literal["recorded", "on_file", "not_researched", "searched_not_found", "not_on_file"]
EVIDENCE: frozenset[str] = frozenset({"recorded", "on_file"})
# The checklist in prompts/funder_assessor.md; a code outside it splits a comparison table.
CheckCode = Literal[
    "area", "theme", "programme",
    "reg_12a", "reg_80g", "darpan", "pan", "reg_no", "csr_1", "fcra",
    "audits_3y", "itr_7", "turnover", "board", "team_cvs", "projects_3", "funder_bar",
]


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CheckCode = Field(description="the checklist item, e.g. area, theme, reg_12a, audits_3y")
    outcome: Outcome
    basis: Basis
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
            return self
        if self.basis not in EVIDENCE:
            raise ValueError(f"{self.code}: {self.basis} is missing evidence, so the outcome is unknown")
        if not self.cites:
            raise ValueError(f"{self.code}: a {self.outcome} must cite the rows it rests on")
        return self


class FunderAssessment(BaseModel):
    """One organisation against one funder."""

    model_config = ConfigDict(extra="forbid")

    org_id: int
    funder_id: int
    funder_name: str
    fit_tier: Literal["strong", "possible", "weak", "not_enough_recorded"]
    reasons: list[str] = Field(description="why this tier, one line each, cited")
    checks: list[Check]
    gaps: list[str] = Field(default_factory=list, description="what to record or upload next, most important first")
