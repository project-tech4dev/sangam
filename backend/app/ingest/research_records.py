"""What a researcher returns: findings shaped like the rows they become.

A finding used to be a label and a value, both strings, and promote.py bridged
the gap to a relational row with regular expressions — sniffing for the word
"crore" to decide a scale, grepping a label for a fiscal year, keyword-matching
to pick a column. That is how a figure becomes wrong by a factor of ten
million, which this codebase has shipped twice.

So the shape is fixed at the source instead. One model per concept, its fields
taken from the target table's columns (app/ingest/expectations.py derives that
list from the SQL catalog, and a test holds the two together). The writer then
maps rather than parses.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 'stated_geography' is where a funder SAYS it prioritises; 'footprint' is where
# money demonstrably went. Keeping them apart is the distinction the whole agent
# runs on, so they are two concepts and two tables, never one.
CONCEPTS = (
    "identity", "identifier", "csr_year", "csr_spend", "footprint", "stated_geography",
    "partner", "program", "grant", "metric", "contact", "document",
)
Concept = Literal[
    "identity", "identifier", "csr_year", "csr_spend", "footprint", "stated_geography",
    "partner", "program", "grant", "metric", "contact", "document",
]
FISCAL_YEAR = re.compile(r"^FY\d{4}-\d{2}$")

SCHEMA_VERSION = 2
"""Bumped when the finding shape changes. Version 1 rows are flat label/value
pairs: still readable, not promotable, re-researched rather than migrated."""

_UNITS: dict[str, int] = {"inr": 1, "lakh": 1_00_000, "crore": 1_00_00_000}


class Money(BaseModel):
    """An amount and the unit it was printed in, converted in exactly one place.

    "Rs 1,068.03 crore" read as 1068.03 is the ten-million-fold error, and no
    amount of keyword-sniffing downstream reliably catches it. So the unit is
    not inferred from the text — it is a field, and the source's own wording is
    kept beside it so a person can check.
    """

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0, description="the number as printed, e.g. 1068.03")
    unit: Literal["inr", "lakh", "crore"] = Field(description="the unit that number is in")
    text: str = Field(min_length=1, description="verbatim, e.g. 'Rs 1,068.03 crore'")

    @property
    def inr(self) -> float:
        """The only conversion. Column contract for every amount here is INR."""
        return self.value * _UNITS[self.unit]


def to_inr(money: dict[str, Any] | None) -> float | None:
    """A Money finding in its stored jsonb form, as INR.

    Findings come back out of jsonb as plain dicts, and every caller that
    needed a number was re-deriving the unit table. There is one table.
    """
    if not money or money.get("unit") not in _UNITS:
        return None
    return float(money["value"]) * _UNITS[money["unit"]]


class FindingBase(BaseModel):
    """Evidence is not optional. A number with no sentence behind it is not a
    finding, and the length floor is what stops 'see report' standing in for one."""

    model_config = ConfigDict(extra="forbid")

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


class YearlyFinding(FindingBase):
    fiscal_year: str = Field(description="FY2024-25. Never mix years in one record")

    @field_validator("fiscal_year")
    @classmethod
    def _fy(cls, v: str) -> str:
        if not FISCAL_YEAR.match(v):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {v!r}")
        return v


class PlacedFinding(FindingBase):
    """A state is enough to resolve; a district without its state is not."""

    state: str = Field(min_length=2, description="the state as the source names it")
    district: str | None = Field(
        default=None, description="only when the source is that precise; never inferred from a city"
    )


class IdentityFinding(FindingBase):
    concept: Literal["identity"] = "identity"
    name: str = Field(min_length=2, description="the legal name as the strongest source writes it")
    funder_type: (
        Literal["corporate_csr", "corporate_foundation", "private_foundation",
                "family_trust", "family_trust_network", "other"] | None
    ) = None
    section_135_bound: bool | None = Field(default=None, description="null means unknown, not false")
    website: str | None = None
    parent_name: str | None = Field(
        default=None,
        description="the company a foundation belongs to. NEVER merge the two — they are two rows",
    )


class IdentifierFinding(FindingBase):
    concept: Literal["identifier"] = "identifier"
    id_type: Literal["pan", "cin", "csr1", "darpan", "reg_no", "domain", "name"]
    id_value: str = Field(min_length=2, description="exactly as printed. Never guess an identifier")


class CsrYearFinding(YearlyFinding):
    """One fiscal year of the statutory CSR annexure. Obligation, budget, spend,
    overhead and unspent are separate items and are never interchangeable."""

    concept: Literal["csr_year"] = "csr_year"
    section_135_applicable: bool | None = None
    average_net_profit: Money | None = None
    prescribed_csr: Money | None = Field(default=None, description="item 5(b), the 2% obligation")
    spent_on_projects: Money | None = None
    admin_overheads: Money | None = None
    impact_assessment_cost: Money | None = None
    total_spent: Money | None = Field(default=None, description="item 6(d)")
    unspent_transferred: Money | None = None
    excess_spent: Money | None = None
    impact_assessment_done: bool | None = None
    notes: str | None = None


class CsrSpendFinding(YearlyFinding):
    """A project, or an aggregate. Never divide an aggregate across projects."""

    concept: Literal["csr_spend"] = "csr_spend"
    amount: Money
    project_name: str | None = Field(
        default=None, description="null on an aggregate row; set for a single project"
    )
    project_count: int | None = Field(
        default=None, description="set on an aggregate: how many projects the amount covers"
    )
    state: str | None = None
    district: str | None = None
    sector: str | None = Field(
        default=None, description="the funder's own words for the theme, not a normalised tag"
    )
    program_name: str | None = None
    designation: str | None = Field(
        default=None, description="e.g. 'aspirational_district', when the total is limited to those"
    )
    implementing_agency: str | None = Field(default=None, description="as printed")
    agency_csr1: str | None = None
    via_agency: bool | None = Field(default=None, description="false means implemented directly")
    is_ongoing: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _aggregate_or_project(self) -> CsrSpendFinding:
        if self.project_name and self.project_count:
            raise ValueError(
                "a row is either one project or an aggregate of several, not both. Drop "
                "project_count, or drop project_name and keep the total"
            )
        return self


class FootprintFinding(YearlyFinding, PlacedFinding):
    """Where a theme actually ran. The strongest evidence of real geography."""

    concept: Literal["footprint"] = "footprint"
    program_name: str | None = None
    name_as_printed: str | None = Field(
        default=None, description="the place name as the report spelled it"
    )
    notes: str | None = None


class StatedGeographyFinding(PlacedFinding):
    """Where the funder SAYS it prioritises. Not evidence that money went there."""

    concept: Literal["stated_geography"] = "stated_geography"
    role: Literal["registered", "operates", "funds", "priority"] = "priority"
    note: str | None = None


class PartnerFinding(YearlyFinding):
    """Keep the year: repeated appearances mean renewal, and collapsing them destroys that."""

    concept: Literal["partner"] = "partner"
    partner_name: str = Field(min_length=2, description="as printed in the source")
    partner_canonical: str | None = Field(
        default=None, description="one spelling per partner; count renewals on this"
    )
    partner_kind: (
        Literal["ngo", "foundation", "university", "research", "government",
                "armed_forces", "hospital", "network", "company", "other"] | None
    ) = None
    partner_csr1: str | None = None
    program_name: str | None = None
    notes: str | None = None


class ProgramFinding(FindingBase):
    concept: Literal["program"] = "program"
    name: str = Field(min_length=2)
    kind: Literal["theme", "programme", "phase", "project"] = "programme"
    parent_name: str | None = Field(
        default=None, description="the theme or programme above this one, when the source says so"
    )
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_enabler: bool | None = None


class GrantFinding(FindingBase):
    """A funder gave money to a named organisation. A named partner is NOT a grant."""

    concept: Literal["grant"] = "grant"
    recipient_name: str = Field(min_length=2, description="the organisation that received it")
    title: str = Field(min_length=2)
    status: Literal["active", "concluded", "unconfirmed", "dormant"] = "unconfirmed"
    amount: Money | None = Field(default=None, description="null means not public. Never zero")
    currency: str = "INR"
    start_date: date | None = None
    end_date: date | None = None
    program_name: str | None = None
    notes: str | None = None


class MetricFinding(FindingBase):
    concept: Literal["metric"] = "metric"
    name: str = Field(min_length=2)
    value: float | None = None
    target: float | None = None
    unit: str | None = None
    period: str | None = Field(default=None, description="'FY2023-24', or 'cumulative to 2026'")
    stage: (
        Literal["input", "output", "adoption", "outcome",
                "sustained_outcome", "impact", "sroi"] | None
    ) = None
    method: (
        Literal["self_reported", "monitoring_data", "survey", "comparison_study",
                "third_party_evaluation", "estimate"] | None
    ) = None
    is_self_reported: bool = Field(
        default=True, description="never describe a self-reported figure as independently verified"
    )
    baseline: float | None = None
    comparison_value: float | None = None
    chain_key: str | None = Field(default=None, description="rows sharing this form one results chain")
    sequence: int | None = None
    program_name: str | None = None
    state: str | None = None
    district: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _a_metric_needs_a_number(self) -> MetricFinding:
        # The DDL says the same: CHECK (value IS NOT NULL OR target IS NOT NULL).
        if self.value is None and self.target is None:
            raise ValueError(f"metric {self.name!r} has neither a value nor a target")
        return self


class ContactFinding(FindingBase):
    """Publicly disclosed CSR roles only. No private personal data."""

    concept: Literal["contact"] = "contact"
    name: str = Field(min_length=2)
    kind: Literal["office_bearer", "programme", "grants", "other"] = "other"
    role: str | None = None
    notes: str | None = None


class DocumentFinding(FindingBase):
    concept: Literal["document"] = "document"
    title: str = Field(min_length=2)
    doc_type: str = Field(min_length=2, description="annual_report | csr_annexure | brsr | …")
    as_of: str | None = Field(
        default=None, description="the period the document describes — not when you read it"
    )


Finding = Annotated[
    IdentityFinding | IdentifierFinding | CsrYearFinding | CsrSpendFinding | FootprintFinding
    | StatedGeographyFinding | PartnerFinding | ProgramFinding | GrantFinding | MetricFinding
    | ContactFinding | DocumentFinding,
    Field(discriminator="concept"),
]

FINDING_MODELS: dict[str, type[FindingBase]] = {
    "identity": IdentityFinding, "identifier": IdentifierFinding, "csr_year": CsrYearFinding,
    "csr_spend": CsrSpendFinding, "footprint": FootprintFinding,
    "stated_geography": StatedGeographyFinding, "partner": PartnerFinding,
    "program": ProgramFinding, "grant": GrantFinding, "metric": MetricFinding,
    "contact": ContactFinding, "document": DocumentFinding,
}


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
    goals: list[str] = Field(
        default_factory=list,
        description="what you set out to find, from research_goals, one line each",
    )
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

    def by_concept(self, concept: str) -> list[FindingBase]:
        return [f for f in self.findings if f.concept == concept]

    def concepts_found(self) -> list[str]:
        return sorted({f.concept for f in self.findings})


class ResearchSummary(BaseModel):
    """What a subagent hands back to the parent, and what the Import board reads.

    Deliberately thin. The findings themselves reach the database through
    save_research, so returning them again would make the model emit the whole
    payload twice — and a union this large as a response_format fails hard,
    losing the task, where a tool error comes back and gets corrected.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    entity_name: str
    canonical_name: str | None = None
    status: Literal["complete", "partial", "not_found", "wrong_entity"]
    stopped_reason: str | None = None
    # Required, not defaulted: a model that omits it would put "0 facts" on
    # the board next to a researcher that found thirty.
    fact_count: int
    source_count: int = 0
    concepts_found: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    saved: bool = Field(default=False, description="true only if save_research returned success")
