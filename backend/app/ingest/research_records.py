"""What a researcher returns: findings, each with the sentence behind it."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONCEPTS = (
    "identity", "identifier", "csr_year", "csr_spend", "footprint", "partner",
    "program", "grant", "metric", "contact", "document",
)
Concept = Literal[
    "identity", "identifier", "csr_year", "csr_spend", "footprint", "partner",
    "program", "grant", "metric", "contact", "document",
]
FISCAL_YEAR = re.compile(r"^FY\d{4}-\d{2}$")


class Finding(BaseModel):
    """One fact, and the evidence for it. A fact with no sentence behind it is
    not a finding — the validators below refuse it rather than storing it."""

    model_config = ConfigDict(extra="forbid")

    concept: Concept
    label: str = Field(min_length=1, description="what this is, e.g. 'CIN' or 'FY2024-25 spent'")
    value: str = Field(min_length=1, description="the value, normalised; amounts in INR")
    fiscal_year: str | None = Field(default=None, description="FY2024-25, when the fact has one")
    evidence: str = Field(min_length=20, description="the sentence from the source that states it")
    source_url: str = Field(min_length=1)
    source_name: str | None = None
    confidence: Literal["high", "medium", "low"]
    basis: Literal["explicit", "derived", "inferred"] = "explicit"

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be an http(s) URL, got {v!r}")
        return v

    @field_validator("fiscal_year")
    @classmethod
    def _fy(cls, v: str | None) -> str | None:
        if v is not None and not FISCAL_YEAR.match(v):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {v!r}")
        return v


class EntityResearch(BaseModel):
    """One organisation, researched once."""

    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=2, description="the name as it was asked for")
    canonical_name: str | None = Field(default=None, description="as the strongest source writes it")
    entity_kind: Literal["funder", "org", "unknown"] = "unknown"
    website: str | None = None
    status: Literal["complete", "partial", "not_found", "wrong_entity"]
    stopped_reason: str | None = Field(
        default=None, description="why research ended where it did, e.g. 'budget spent'"
    )
    summary: str = Field(min_length=20, description="a few sentences, factual, no judgement")
    findings: list[Finding] = Field(default_factory=list)
    not_found: list[str] = Field(
        default_factory=list, description="concepts looked for and not found"
    )
    sources_read: list[str] = Field(default_factory=list)

    @field_validator("not_found")
    @classmethod
    def _known_concepts(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(CONCEPTS))
        if unknown:
            raise ValueError(f"unknown concepts in not_found: {unknown}; allowed: {list(CONCEPTS)}")
        return v

    @model_validator(mode="after")
    def _complete_means_something_was_found(self) -> EntityResearch:
        # A field validator would not run here: `findings` defaults to [], and
        # pydantic skips validators on defaults. A "complete" result with
        # nothing in it is a contradiction — the honest shapes are 'not_found',
        # or 'partial' with a reason.
        if self.status == "complete" and not self.findings:
            raise ValueError("status 'complete' with no findings — use 'not_found' or 'partial'")
        if self.status in ("partial", "wrong_entity") and not self.stopped_reason:
            raise ValueError(f"status {self.status!r} needs a stopped_reason saying why")
        return self

    def by_concept(self, concept: str) -> list[Finding]:
        return [f for f in self.findings if f.concept == concept]
