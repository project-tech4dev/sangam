"""What an adapter or a sub-agent may propose. The writer accepts nothing else."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FISCAL_YEAR = re.compile(r"^FY\d{4}-\d{2}$")


class Provenance(BaseModel):
    """Every fact row carries its source. A record without one is never written."""

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    fetched_at: datetime
    as_of: str | None = None
    archive_url: str | None = None

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
    identifiers: dict[str, str] = Field(default_factory=dict)
    """Deterministic keys: cin, pan, csr1, darpan, reg_no, domain."""

    @field_validator("name")
    @classmethod
    def _one_organisation(cls, v: str) -> str:
        return reject_if_aggregate(v)

    @field_validator("identifiers")
    @classmethod
    def _known_types(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"pan", "cin", "csr1", "darpan", "reg_no", "domain", "name"}
        unknown = sorted(set(v) - allowed)
        if unknown:
            raise ValueError(f"unknown identifier types: {unknown}; allowed: {sorted(allowed)}")
        return v


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

    @field_validator("prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred")
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
    """A project, or an aggregate of several. Never both, and never divided."""

    kind: Literal["funder_csr_spend"] = "funder_csr_spend"
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    amount: float = Field(ge=0, description="INR")
    project_name: str | None = None
    project_count: int | None = None
    state: str | None = None
    district: str | None = None
    program_name: str | None = None
    designation: str | None = None
    implementing_agency: str | None = None
    agency_csr1: str | None = None
    via_agency: bool | None = None
    is_ongoing: bool | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class FunderFootprintRecord(Provenance):
    """Where a theme actually ran. location_id is NOT NULL, so a place that
    will not resolve is a row that cannot be written — say so, do not guess."""

    kind: Literal["funder_footprint"] = "funder_footprint"
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
    """A named partner. NOT proof that money changed hands — that is a grant."""

    kind: Literal["funder_partner"] = "funder_partner"
    funder_name: str = Field(min_length=2)
    fiscal_year: str
    partner_name: str = Field(min_length=2)
    partner_canonical: str | None = None
    partner_kind: str | None = None
    partner_csr1: str | None = None
    program_name: str | None = None
    notes: str | None = None

    _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class ProgramRecord(Provenance):
    kind: Literal["program"] = "program"
    funder_name: str = Field(min_length=2)
    name: str = Field(min_length=2)
    program_kind: Literal["theme", "programme", "phase", "project"] = "programme"
    parent_name: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_enabler: bool | None = None

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class MetricRecord(Provenance):
    kind: Literal["metric"] = "metric"
    funder_name: str = Field(min_length=2)
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

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


class ContactRecord(Provenance):
    """Publicly disclosed roles only. Email and phone are deliberately absent."""

    kind: Literal["contact"] = "contact"
    funder_name: str = Field(min_length=2)
    name: str = Field(min_length=2)
    contact_kind: Literal["office_bearer", "programme", "grants", "other"] = "other"
    role: str | None = None
    notes: str | None = None

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))


Record = (
    FunderRecord | FunderCsrYearRecord | NewsMentionRecord | FunderCsrSpendRecord
    | FunderFootprintRecord | FunderLocationRecord | FunderPartnerRecord | ProgramRecord
    | MetricRecord | ContactRecord
)
