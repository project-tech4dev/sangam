"""What an adapter or a sub-agent may propose. The writer accepts nothing else."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest.expectations import activity_kind

FISCAL_YEAR = re.compile(r"^FY\d{4}-\d{2}$")
# What an inferred domain and theme rest on (funder_activity.classified_by).
ClassifiedBy = Literal["filed_sector", "project_name", "partner", "report"]
ImplementationMode = Literal["direct", "implementing_agency", "own_trust_or_section8", "not_stated"]
# A company's Corporate Identity Number: listing status, industry code, state, year, type, serial.
CIN_FORMAT = re.compile(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}")


def normalise_cin(v: str) -> str:
    """One spelling per CIN: upper case, no spaces. The MCA prints it both ways."""
    return re.sub(r"\s+", "", v).upper()


class Provenance(BaseModel):
    """Every fact row carries its source. A record without one is never written."""

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    fetched_at: datetime
    as_of: str | None = None
    archive_url: str | None = None
    # Only the baseline tables have these two columns; the writers that target
    # a table without them simply do not pass them.
    content_hash: str | None = None
    extractor_version: str | None = None

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be an http(s) URL, got {v!r}")
        return v


# An article's subject is often a market, not an organisation. "NSE-listed
# companies spent Rs 22,212 crore" is a real sentence with a real number and no
# funder in it, and writing it as one puts a fictional entity in the catalog.
_AGGREGATE = re.compile(
    r"\b(companies|corporates|firms|enterprises|psus|organisations|organizations"
    r"|conglomerates|entities|listed|india inc|corporate india|sector|industry"
    r"|top\s+\d+|nifty|sensex|bse|nse)\b",
    re.IGNORECASE,
)


def reject_if_aggregate(name: str) -> str:
    """A class of companies is not a funder. Raises so no path can write one."""
    if _AGGREGATE.search(name):
        raise ValueError(
            f"{name!r} names a group of companies, not one organisation. A market total "
            f"is not a funder's spend; report it, do not record it as an entity."
        )
    return name


def _fiscal_year(v: str) -> str:
    if not FISCAL_YEAR.match(v):
        raise ValueError(f"fiscal_year must look like 'FY2023-24', got {v!r}")
    return v


class FunderRecord(Provenance):
    kind: Literal["funder"] = "funder"
    name: str = Field(min_length=2)
    funder_type: str | None = None
    website: str | None = None
    section_135_bound: bool | None = None
    parent_name: str | None = None
    """The company a foundation belongs to. Resolved to funders.parent_id by the
    caller, which reports it rather than inventing a row when it will not
    resolve: Axis Bank Foundation and Axis Bank Limited are two rows and a link,
    never one row, and a placeholder parent is a fact nobody sourced."""
    cin: str | None = None
    """Corporate funders only. Normalised here and refused on the finding, so a malformed CIN costs
    one field at save time rather than the whole funder at promotion."""
    aliases: list[str] = Field(default_factory=list)
    intake_mode: Literal["open", "rolling", "invitation_only", "rfp_only", "closed", "unknown"] | None = None
    funds_external: bool | None = None
    typical_duration_months: int | None = Field(default=None, gt=0)
    grant_size_min: float | None = Field(default=None, ge=0, description="INR")
    grant_size_max: float | None = Field(default=None, ge=0, description="INR")

    @field_validator("cin")
    @classmethod
    def _one_spelling(cls, v: str | None) -> str | None:
        return normalise_cin(v) if v else None

    @field_validator("aliases")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for alias in (a.strip() for a in v):
            if alias and alias.lower() not in seen:
                seen.add(alias.lower())
                out.append(alias)
        return out

    @field_validator("name")
    @classmethod
    def _one_organisation(cls, v: str) -> str:
        return reject_if_aggregate(v)


class FunderCsrYearRecord(Provenance):
    """Amounts are INR, not crore. funder_csr_years declares INR, and an article
    printing "Rs 530.11 crore" is 5_301_100_000 — the conversion happens once,
    in the extractor."""

    kind: Literal["funder_csr_year"] = "funder_csr_year"
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    prescribed_csr: float | None = None
    total_spent: float | None = None
    average_net_profit: float | None = None
    unspent_transferred: float | None = None
    # Items 6(a)-(c) and 6(f) of the statutory annexure. The researcher has
    # always collected these; until now the writer dropped them silently.
    spent_on_projects: float | None = None
    admin_overheads: float | None = None
    impact_assessment_cost: float | None = None
    excess_spent: float | None = None
    local_area_spent: float | None = None
    impact_assessment_done: bool | None = None
    section_135_applicable: bool | None = None
    notes: str | None = None

    @field_validator("funder_name")
    @classmethod
    def _one_organisation(cls, v: str) -> str:
        return reject_if_aggregate(v)

    @field_validator("fiscal_year")
    @classmethod
    def _format(cls, v: str) -> str:
        if not FISCAL_YEAR.match(v):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {v!r}")
        return v

    @field_validator(
        "prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred",
        "spent_on_projects", "admin_overheads", "impact_assessment_cost", "excess_spent",
        "local_area_spent",
    )
    @classmethod
    def _non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("CSR amounts cannot be negative")
        return v


class NewsMentionRecord(Provenance):
    kind: Literal["news_mention"] = "news_mention"
    url: str = Field(min_length=1)
    title: str | None = None
    seendate: datetime | None = None
    domain: str | None = None
    funder_name: str | None = None
    summary: str | None = None
    topic: str | None = None


# --- The funder-side fact tables -------------------------------------------
#
# One class per table, fields named for its columns. Amounts are INR: the
# researcher states a unit, Money.inr converts once, and what arrives here is
# already converted. Place names arrive as words and app/ingest/geography.py
# turns them into a locations id, because a report says "Barpeta, Assam" and
# the column is a foreign key.


class FunderCsrSpendRecord(Provenance):
    """One spend line: a project, or an aggregate of several. Never both, and never divided."""

    kind: Literal["funder_csr_spend"] = "funder_csr_spend"
    activity_kind: ClassVar[str] = activity_kind("csr_spend")
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    amount: float = Field(ge=0, description="INR")
    outlay: float | None = Field(default=None, ge=0, description="INR")
    project_name: str | None = None
    project_count: int | None = None
    state: str | None = None
    district: str | None = None
    program_name: str | None = None
    designation: str | None = None
    implementation_mode: ImplementationMode | None = None
    partner_name: str | None = None
    partner_csr1: str | None = None
    is_ongoing: bool | None = None
    notes: str | None = None
    domain: str
    theme: str | None = None
    classified_by: ClassifiedBy
    classification_note: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class FunderFootprintRecord(Provenance):
    """Where a theme actually ran. A line needs a place, so a place that will not resolve is a line
    that cannot be written — say so, do not guess."""

    kind: Literal["funder_footprint"] = "funder_footprint"
    activity_kind: ClassVar[str] = activity_kind("footprint")
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    state: str = Field(min_length=2)
    district: str | None = None
    program_name: str | None = None
    name_as_printed: str | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class FunderLocationRecord(Provenance):
    """A STATED priority. Not evidence that money went there."""

    kind: Literal["funder_location"] = "funder_location"
    funder_name: str = Field(min_length=2)
    state: str = Field(min_length=2)
    district: str | None = None
    role: Literal["registered", "operates", "funds", "priority"] = "priority"
    note: str | None = None

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class FunderPartnerRecord(Provenance):
    """A named partner. With an amount, what the partner received from this funder that year (INR);
    without one, NOT proof that money changed hands."""

    kind: Literal["funder_partner"] = "funder_partner"
    activity_kind: ClassVar[str] = activity_kind("partner")
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    partner_name: str = Field(min_length=2)
    partner_canonical: str | None = None
    partner_kind: str | None = None
    partner_csr1: str | None = None
    outlay: float | None = Field(default=None, ge=0, description="INR")
    amount: float | None = Field(default=None, ge=0, description="INR")
    program_name: str | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class FunderProgrammeSpendRecord(Provenance):
    """The funder's own programme total for a year (D12)."""

    kind: Literal["funder_programme_spend"] = "funder_programme_spend"
    activity_kind: ClassVar[str] = activity_kind("programme_spend")
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    program_name: str = Field(min_length=2)
    amount: float = Field(ge=0, description="INR")
    domain: str
    theme: str | None = None
    classified_by: ClassifiedBy
    classification_note: str | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class ProgramRecord(Provenance):
    kind: Literal["program"] = "program"
    entity_name: str = Field(min_length=2)
    name: str = Field(min_length=2)
    program_kind: Literal["theme", "programme", "phase", "project"] = "programme"
    parent_name: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_enabler: bool | None = None

    _org = field_validator("entity_name")(lambda v: reject_if_aggregate(v))


class MetricRecord(Provenance):
    kind: Literal["metric"] = "metric"
    entity_name: str = Field(min_length=2)
    name: str = Field(min_length=2)
    value: float | None = None
    target: float | None = None
    unit: str | None = None
    period: str | None = None
    stage: str | None = None
    method: str | None = None
    is_self_reported: bool = True
    baseline: float | None = None
    comparison_value: float | None = None
    chain_key: str | None = None
    sequence: int | None = None
    program_name: str | None = None
    state: str | None = None
    district: str | None = None
    notes: str | None = None

    _org = field_validator("entity_name")(lambda v: reject_if_aggregate(v))


class ContactRecord(Provenance):
    """Publicly disclosed roles, and a shared mailbox when one is published.

    Phone is still deliberately absent, and `email` reaches this record only
    after ContactFinding refused anything that reads as an individual's
    address. The SQL catalog still omits both columns, so Ask Sangam cannot
    select them.
    """

    kind: Literal["contact"] = "contact"
    entity_name: str = Field(min_length=2)
    name: str = Field(min_length=2)
    contact_kind: Literal["office_bearer", "programme", "grants", "other"] = "other"
    role: str | None = None
    email: str | None = None
    is_role_mailbox: bool = False
    notes: str | None = None

    _org = field_validator("entity_name")(lambda v: reject_if_aggregate(v))


class FunderEligibilityRecord(Provenance):
    """One condition a funder sets for applicants. Its standing bar, not a call's."""

    kind: Literal["funder_eligibility"] = "funder_eligibility"
    funder_name: str = Field(min_length=2)
    # `kind` is taken by the discriminator above, so the finding's own `kind`
    # arrives renamed — same reason program_kind and contact_kind are renamed.
    criterion_kind: Literal["statutory_restatement", "own_bar", "disqualifier"]
    criterion: str = Field(min_length=10)
    notes: str | None = None

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class RfpRecord(Provenance):
    """An open call for proposals. The one concept an NGO can act on today."""

    kind: Literal["rfp"] = "rfp"
    funder_name: str = Field(min_length=2)
    title: str = Field(min_length=4)
    status: Literal["open", "closed", "removed"] = "open"
    url: str | None = None
    deadline: date | None = None
    amount_min: float | None = Field(default=None, ge=0, description="INR")
    amount_max: float | None = Field(default=None, ge=0, description="INR")
    eligibility: list[str] = Field(default_factory=list)
    state: str | None = None
    district: str | None = None
    sector: str | None = None

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))

    @model_validator(mode="after")
    def _band_is_the_right_way_round(self) -> RfpRecord:
        both = self.amount_min is not None and self.amount_max is not None
        if both and self.amount_max < self.amount_min:
            raise ValueError(
                f"grant band is inverted: min {self.amount_min} above max {self.amount_max}"
            )
        return self


# --- The org side ------------------------------------------------------------
#
# An organisation that RECEIVES money. Same writer discipline as the funder
# records: typed, provenance-carrying, and refusing anything the writer cannot
# turn into a column.

ORG_ID_TYPES = frozenset({"pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no"})


class OrgRecord(Provenance):
    """An NGO. No website field: `orgs` has no column for one, and promotion
    reports that rather than dropping it quietly."""

    kind: Literal["org"] = "org"
    name: str = Field(min_length=2)
    org_kind: Literal["cso", "intermediary", "government"] | None = None
    """None, not "cso". orgs.org_kind is NOT NULL DEFAULT 'cso', so a default
    here would reach _blanks as a stated finding and contradict every
    intermediary and government row the cohort holds."""
    legal_form: str | None = None
    registration_date: date | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    """12A, 80G and FCRA; a funder has no room for them."""

    @field_validator("name")
    @classmethod
    def _one_organisation(cls, v: str) -> str:
        return reject_if_aggregate(v)

    @field_validator("identifiers")
    @classmethod
    def _known_types(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(v) - ORG_ID_TYPES)
        if unknown:
            raise ValueError(
                f"unknown identifier types: {unknown}; allowed: {sorted(ORG_ID_TYPES)}"
            )
        return v


class OrgFinancialsRecord(Provenance):
    """Amounts are INR, like every other record here. The org analogue of
    FunderCsrYearRecord: one row per fiscal year, keyed on (org_id, fiscal_year)."""

    kind: Literal["org_financials"] = "org_financials"
    entity_name: str = Field(min_length=2)
    fiscal_year: str
    total_income: float | None = None
    program_spend: float | None = None
    non_program_spend: float | None = None
    foreign_contribution: float | None = None
    is_audited: bool | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _one = field_validator("entity_name")(lambda v: reject_if_aggregate(v))


class OrgLocationRecord(Provenance):
    """Where an NGO is registered or works. org_locations.role has no
    'priority' value, unlike the funder side — an NGO states where it works,
    not where it would like to fund."""

    kind: Literal["org_location"] = "org_location"
    entity_name: str = Field(min_length=2)
    state: str = Field(min_length=2)
    district: str | None = None
    role: Literal["registered", "operates", "funds"] = "operates"
    note: str | None = None

    _one = field_validator("entity_name")(lambda v: reject_if_aggregate(v))


Record = (
    FunderRecord | OrgRecord | OrgFinancialsRecord | OrgLocationRecord
    | FunderCsrYearRecord | NewsMentionRecord | FunderCsrSpendRecord
    | FunderFootprintRecord | FunderLocationRecord | FunderPartnerRecord | FunderProgrammeSpendRecord
    | ProgramRecord
    | MetricRecord | ContactRecord | RfpRecord
)
