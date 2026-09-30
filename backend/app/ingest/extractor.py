"""Per-source extraction agents: raw text in, typed records out.

One of these runs per source, concurrently. The model's whole output is a
pydantic object — it never sees SQL and never names a table.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.ingest.records import FunderCsrYearRecord

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """You read one Indian CSR news article and report only what it states.

Return the CSR figures the article gives for a named company or foundation. Rules:
- Only figures the article actually states. Never infer, convert or carry a number over from
  another year. If the article gives no rupee figure for a named funder, return nothing.
- Report EVERY year the article states, not just the most recent one. A piece comparing
  "₹427 crore in FY25, up from ₹269 crore in FY24" carries two years: return both.
- Report every named funder the article gives figures for, not only the one you were
  looking for. A comparison piece often carries several.
- Amounts in INR crore, as printed. '₹530.11 crore' is 530.11.
- fiscal_year is 'FYyyyy-yy'. 'FY26', 'FY2026' and 'FY 2025-26' all mean FY2025-26;
  'FY 2025' in Indian CSR reporting means FY2024-25. If the year is ambiguous, return nothing.
- funder_name exactly as the article writes it, e.g. 'Axis Bank Limited'.
- prescribed_csr is the 2% obligation; total_spent is what was actually spent.

Article title: {title}
Published: {published}
Text: {text}
"""


# Articles print crore; funder_csr_years stores INR, as its column comments say
# and as the reference seed writes it. Converting in exactly one place is what
# keeps a model reading "₹530.11 crore" from landing as 530.11 rupees.
CRORE = 10_000_000


class ExtractedYear(BaseModel):
    """One funder-year of CSR figures, as the article states them, in CRORE."""

    funder_name: str = Field(description="the company or foundation, as printed")
    fiscal_year: str = Field(description="FYyyyy-yy")
    prescribed_csr: float | None = Field(default=None, description="the 2% obligation, INR crore")
    total_spent: float | None = Field(default=None, description="actually spent, INR crore")
    average_net_profit: float | None = Field(default=None, description="INR crore")
    unspent_transferred: float | None = Field(default=None, description="INR crore")


class Extraction(BaseModel):
    years: list[ExtractedYear] = Field(default_factory=list)


def _inr(crore: float | None) -> float | None:
    return None if crore is None else round(crore * CRORE, 2)


async def extract_csr_years(model: Any, item: dict[str, Any]) -> list[FunderCsrYearRecord]:
    """Returns [] when the article carries no figure — that is the common case."""
    structured = model.with_structured_output(Extraction)
    result = await structured.ainvoke(
        EXTRACT_PROMPT.format(
            title=item["title"], published=item.get("published"), text=item["text"][:5000]
        )
    )
    records: list[FunderCsrYearRecord] = []
    for year in result.years:
        try:
            printed = ", ".join(
                f"{label} Rs {value} crore"
                for label, value in (
                    ("obligation", year.prescribed_csr),
                    ("spent", year.total_spent),
                    ("avg net profit", year.average_net_profit),
                    ("unspent", year.unspent_transferred),
                )
                if value is not None
            )
            records.append(
                FunderCsrYearRecord(
                    funder_name=year.funder_name,
                    fiscal_year=year.fiscal_year,
                    prescribed_csr=_inr(year.prescribed_csr),
                    total_spent=_inr(year.total_spent),
                    average_net_profit=_inr(year.average_net_profit),
                    unspent_transferred=_inr(year.unspent_transferred),
                    source_url=item["url"],
                    source_name=item["source_name"],
                    fetched_at=item["fetched_at"],
                    as_of=year.fiscal_year,
                    # The printed wording is kept: a figure read back as INR
                    # should still be checkable against what the article said.
                    notes=f"As printed: {printed}. From: {item['title'][:160]}",
                )
            )
        except ValueError as exc:
            # A malformed record is dropped here, not written and not raised: the
            # run reports it, and one bad article never fails a whole source.
            logger.info("dropped an extracted row from %s: %s", item["url"], exc)
    return records
