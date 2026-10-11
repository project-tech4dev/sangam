"""One organisation against one funder under match-v2. rules.py judges each criterion; rubric.py counts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.matching import rubric

Code = Literal["theme", "geography", "population", "eligibility", "relationship", "funding_size", "capacity"]


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    points: int | None = Field(description="points earned; null when it could not be judged")
    note: str = Field(description="what was found, in words, including what is missing")
    cites: list[str] = Field(default_factory=list, description="markers of the rows used, e.g. [org:9]")

    @computed_field
    @property
    def label(self) -> str:
        return rubric.CRITERIA[self.code][0]

    @computed_field
    @property
    def max(self) -> int:
        return rubric.maximum(self.code)

    # Computed from points, so a status can never disagree with the arithmetic.
    @computed_field
    @property
    def status(self) -> rubric.Status:
        return rubric.status_for(self.points, self.max)

    @field_validator("cites")
    @classmethod
    def _bracketed(cls, cites: list[str]) -> list[str]:
        return [c if c.startswith("[") else f"[{c.strip()}]" for c in cites]

    @model_validator(mode="after")
    def _evidence_backs_a_verdict(self) -> Criterion:
        if self.points is not None and not 0 <= self.points <= self.max:
            raise ValueError(f"{self.code}: {self.points} is outside 0..{self.max}")
        # An empty cite list is an absence: allowed only where nothing recorded is the finding.
        if self.points is not None and not self.cites and not (self.code == "relationship" and self.points == 0):
            raise ValueError(f"{self.code}: a judged criterion must cite the rows it rests on")
        return self


class Reason(BaseModel):
    kind: Literal["fit", "gap"]
    criterion: str
    text: str


class Match(BaseModel):
    """The spec's card and detail for one pair; score and tier are always arithmetic on the criteria."""

    model_config = ConfigDict(extra="forbid")

    org_id: int
    funder_id: int
    funder_name: str
    funder_type: str | None
    criteria: list[Criterion]
    card: list[Reason]
    summary: str
    not_judged: list[str]
    improve: list[str]

    @model_validator(mode="after")
    def _every_criterion_once_in_order(self) -> Match:
        if [c.code for c in self.criteria] != list(rubric.CRITERIA):
            raise ValueError("criteria must be every rubric criterion, once, in the rubric's order")
        return self

    @computed_field
    @property
    def score(self) -> dict[str, int] | None:
        return rubric.score({c.code: c.points for c in self.criteria})

    @computed_field
    @property
    def tier(self) -> rubric.Tier:
        return rubric.tier(self.score["of_100"] if self.score else None)
