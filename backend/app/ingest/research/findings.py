"""What a researcher saves: its findings with the gaps, the unplaced facts and the summary its parent reads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest.research import source_guards
from app.ingest.research.expectations import concepts_for
from app.ingest.research.finding_types import (
    CONCEPTS,
    FISCAL_YEAR,
    YEARLY,
    Finding,
    FindingBase,
    drop_null_extras,
)


class Gap(BaseModel):
    """Something looked for and not got; the coverage report reads these."""

    model_config = ConfigDict(extra="forbid")

    concept: str = Field(description="a concept from research_goals, e.g. 'rfp' or 'csr_year'")
    fiscal_year: str | None = Field(
        default=None, description="for a year-bound concept, the year missing; empty means every year asked"
    )
    field: str | None = Field(default=None, description="one field, when the concept was found without it")
    reason: Literal["not_stated", "blocked", "not_reached"] = Field(
        description="'blocked' if the source could not be read (403, JS-only page, a staff file that "
                    "failed or was not selected); 'not_stated' if it was read and does not say; "
                    "'not_reached' if the run stopped before looking (name what was left unread)"
    )
    detail: str = Field(min_length=3, description="one sentence: which source, and what happened")

    @field_validator("concept")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in CONCEPTS:
            raise ValueError(f"unknown concept {v!r}; allowed: {list(CONCEPTS)}")
        return v

    @model_validator(mode="after")
    def _year_only_when_yearly(self) -> Gap:
        if self.fiscal_year and self.concept not in YEARLY:
            raise ValueError(f"{self.concept!r} is not by year; leave fiscal_year empty")
        if self.fiscal_year and not FISCAL_YEAR.match(self.fiscal_year):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {self.fiscal_year!r}")
        return self


class Unplaced(BaseModel):
    """A fact a source states that no concept has a field for; the brief shows it, the catalog cannot yet."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=2, description="what it is, e.g. 'registered_address', 'co_funding_share'")
    value: str = Field(min_length=1, description="the value as the source states it")
    evidence: str = Field(min_length=20, description="the sentence from the source that states it")
    source_url: str = Field(min_length=1)
    page: str | None = Field(default=None, max_length=80)

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        return FindingBase._http(v)


class EntityResearch(BaseModel):
    """One organisation, researched once."""

    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=2, description="the name as it was asked for")
    canonical_name: str | None = Field(default=None, description="as the strongest source writes it")
    entity_kind: Literal["funder", "org", "unknown"] = Field(
        description="'funder' if it GIVES money, 'org' if it RECEIVES it. 'unknown' only when "
                    "the research did not get far enough to tell"
    )
    website: str | None = None
    status: Literal["complete", "partial", "not_found", "wrong_entity"]
    stopped_reason: str | None = Field(
        default=None,
        description="REQUIRED when status is 'partial' or 'wrong_entity': why research ended where it did, "
                    "e.g. 'Stopped at the reading limit. Unread: the FY2024-25 annual report'",
    )
    summary: str = Field(min_length=20, description="a few sentences, factual, no judgement")
    goals: list[str] = Field(
        default_factory=list,
        description="what you set out to find, from research_goals, one line each",
    )
    years: list[str] = Field(
        default_factory=list, description="the fiscal years you were asked to cover, e.g. ['FY2024-25']"
    )
    findings: list[Finding] = Field(default_factory=list)
    gaps: list[Gap] = Field(
        default_factory=list,
        description="every concept, year or field you looked for and did not get, with why. "
                    "Unlisted and unfound reads as 'not attempted'",
    )
    sources_read: list[str] = Field(default_factory=list)
    unplaced: list[Unplaced] = Field(
        default_factory=list,
        description="facts a source states that no concept has a field for: never dropped, never forced into one",
    )

    _nulls = model_validator(mode="before")(classmethod(drop_null_extras))

    @field_validator("years")
    @classmethod
    def _fiscal_years(cls, v: list[str]) -> list[str]:
        bad = [y for y in v if not FISCAL_YEAR.match(y)]
        if bad:
            raise ValueError(f"years must look like 'FY2023-24', got {bad}")
        return v

    @property
    def not_found(self) -> list[str]:
        """Concepts with no finding and at least one gap; the brief's 'Looked for, not found'."""
        found = set(self.concepts_found())
        return sorted({g.concept for g in self.gaps if g.concept not in found})

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
        # A run that read enough to report findings read enough to say which
        # kind it was reading about — the two sit in the same first search.
        # 'unknown' survives for not_found and wrong_entity, where it is true.
        if self.status in ("complete", "partial") and self.entity_kind == "unknown":
            raise ValueError(
                f"status {self.status!r} with entity_kind 'unknown' — research that got this far "
                f"knows whether the organisation gives money ('funder') or receives it ('org')"
            )
        if self.entity_kind == "org":
            # An org's shared concepts are ranked at promotion, so the tier is required at save.
            tierless = sorted({f.concept for f in self.findings if f.concept in ("program", "metric", "contact", "partner")
                               and (getattr(f, "source_type", None) is None
                                    or getattr(f, "evidence_tier", None) is None)})
            if tierless:
                raise ValueError(f"an org's {tierless} findings need source_type and evidence_tier")
        return self

    @model_validator(mode="after")
    def _gaps_fit_the_kind(self) -> EntityResearch:
        if self.entity_kind == "unknown":
            return self
        wrong = sorted({g.concept for g in self.gaps} - set(concepts_for(self.entity_kind)))
        if wrong:
            raise ValueError(f"gaps name {wrong}, which a {self.entity_kind} is not researched for; "
                             f"allowed: {list(concepts_for(self.entity_kind))}")
        return self

    @model_validator(mode="after")
    def _sources_are_labelled_honestly(self) -> EntityResearch:
        wrong = source_guards.check_research(self.findings, self.entity_kind)
        if wrong:
            raise ValueError("; ".join(wrong))
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
    # Required for the same reason fact_count is, plus one the parent acts on:
    # it decides whether a catalog-writer is launched at all. An NGO has no
    # writer, so launching one burns a subagent to produce only a refusal.
    entity_kind: Literal["funder", "org", "unknown"]
    # Required, not defaulted: a model that omits it would put "0 facts" on
    # the board next to a researcher that found thirty.
    fact_count: int
    source_count: int = 0
    concepts_found: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    saved: bool = Field(default=False, description="true only if save_research returned success")



class WorkbookEntity(BaseModel):
    """One organisation a staff workbook names, and the cell that names it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["funder", "org", "unknown"]
    marker: str = Field(description="the [source:<document>#<sheet>!<cell>] marker of the cell holding the name")


class VaultResearch(BaseModel):
    """What the vault-reader found in one organisation's own files about one entity."""

    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=2, description="the name as it was asked for, exactly")
    entity_kind: Literal["funder", "org"]
    org_id: int = Field(description="the organisation whose Doc Vault was read, from list_vault_documents")
    documents_read: list[int] = Field(description="every vault document id you read")
    findings: list[Finding] = Field(default_factory=list)
    gaps: list[Gap] = Field(
        default_factory=list, description="each concept you looked for in the files and did not find"
    )

    def concepts_found(self) -> list[str]:
        return sorted({f.concept for f in self.findings})


def _known_concepts(values: list[str]) -> list[str]:
    unknown = [v for v in values if v not in CONCEPTS]
    if unknown:
        raise ValueError(f"not concept names: {unknown}")
    return values


class VaultSummary(BaseModel):
    """What the vault-reader hands back: ids and concept names only, so no private wording leaves it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    saved: bool
    concepts_found: list[str]
    concepts_missing: list[str] = Field(description="concepts from research_goals the files do not answer")
    documents_read: list[int]
    fact_count: int

    _concepts = field_validator("concepts_found", "concepts_missing")(_known_concepts)


class WorkbookEntities(BaseModel):
    """What the workbook-reader hands back: names to research, never figures."""

    model_config = ConfigDict(extra="forbid")

    documents: list[int]
    entities: list[WorkbookEntity]
    complete: bool = Field(description="false when some rows were not read; say which in notes")
    notes: list[str] = Field(default_factory=list)

class TableWrite(BaseModel):
    """One catalog table, and how many rows of it a promotion produced."""

    model_config = ConfigDict(extra="forbid")

    table: str
    rows: int


class PromotionReport(BaseModel):
    """What the catalog-writer hands back: what landed, and what did not.

    Deliberately not a place to put facts. Everything here is read back out of
    the database after the write, so the report describes rows that exist
    rather than rows a model believes it created.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    entity_name: str | None = None
    entity_id: int | None = None
    entity_kind: Literal["funder", "org"] | None = None
    tables_written: list[TableWrite] = Field(default_factory=list)
    rows_written: int
    held_back: list[str] = Field(
        default_factory=list, description="verbatim reasons, each a decision for a person"
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="a source that disagrees with a stored value: both values and both sources, verbatim. "
                    "The stored value was kept",
    )
    still_research: list[str] = Field(
        default_factory=list, description="concepts saved under a shape no writer reads"
    )
    verified: bool = Field(
        default=False, description="true only if the dossier was read back and agreed"
    )
