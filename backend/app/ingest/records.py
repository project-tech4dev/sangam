"""What an adapter or a sub-agent may propose. The writer accepts nothing else."""

from __future__ import annotations

import re
from datetime import datetime
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


Record = FunderRecord | FunderCsrYearRecord | NewsMentionRecord
