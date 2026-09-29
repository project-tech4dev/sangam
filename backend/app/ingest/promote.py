"""Move research findings into the catalog, where a writer exists for them.

Research and catalog are different things. A finding is what a source said,
with the sentence that says it; a catalog row is a fact the product answers
questions from. This is the deliberate step between them, and it only moves
what there is somewhere to move — the rest is reported, not silently dropped.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.ingest.matcher import resolve_funder
from app.ingest.records import FunderCsrYearRecord, FunderRecord
from app.ingest.writer import write_csr_year, write_funder

logger = logging.getLogger(__name__)

# identity/identifier → funders, csr_year → funder_csr_years. Everything else
# has no writer: see docs/INGEST.md.
PROMOTABLE = ("identity", "identifier", "csr_year")
_FY = re.compile(r"FY\d{4}-\d{2}")
_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")
_SPENT = ("spent", "expenditure", "spend")
_OBLIGATION = ("prescribed", "obligation", "2%", "required")


def amount(value: str) -> float | None:
    """The first bare number in a value, or None when it is not a clean figure.

    Findings carry free text — "INR 3,100,000,000,000 (₹3,10,000 crore)" as
    readily as "4270000000". A figure that cannot be read without guessing is
    not promoted; guessing is how a wrong number gets into the catalog.
    """
    match = _NUMBER.search(value.replace(" ", ""))
    if not match:
        return None
    try:
        n = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    # Scale matters more than the digits. "Rs 1,068.03 crore" read as 1068 is
    # the same ten-million-fold error the extractor had, so a small number is
    # only accepted when the text says what unit it is in.
    if n >= 1_00_00_000:
        return n
    lowered = value.lower()
    if "crore" in lowered:
        return n * 1_00_00_000
    if "lakh" in lowered:
        return n * 1_00_000
    return None


def _fiscal_year(finding: dict[str, Any]) -> str | None:
    if finding.get("fiscal_year"):
        return finding["fiscal_year"]
    found = _FY.search(finding.get("label", ""))
    return found.group(0) if found else None


def _provenance(finding: dict[str, Any], fetched: datetime) -> dict[str, Any]:
    return {
        "source_url": finding["source_url"],
        "source_name": finding.get("source_name") or "research",
        "fetched_at": fetched,
    }


def funder_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> FunderRecord | None:
    """One funder record, built from the identity and identifier findings."""
    anchor = next((f for f in findings if f["concept"] in ("identity", "identifier")), None)
    if anchor is None:
        return None
    identifiers: dict[str, str] = {}
    for f in findings:
        if f["concept"] != "identifier":
            continue
        label = f.get("label", "").lower()
        for key in ("cin", "pan", "csr1", "darpan", "reg_no"):
            if key in label.replace("-", "").replace(" ", ""):
                identifiers[key] = f["value"]
                break
    try:
        return FunderRecord(
            name=row["canonical_name"] or row["entity_name"],
            website=row.get("website"),
            identifiers=identifiers,
            as_of=None,
            **_provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("funder record refused for %s: %s", row["slug"], exc)
        return None


def csr_years_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> list[FunderCsrYearRecord]:
    """One record per fiscal year, merging the spent and obligation findings."""
    name = row["canonical_name"] or row["entity_name"]
    by_year: dict[str, dict[str, Any]] = {}
    for f in findings:
        if f["concept"] != "csr_year":
            continue
        year = _fiscal_year(f)
        value = amount(f["value"])
        if not year or value is None:
            continue
        label = f.get("label", "").lower()
        slot = by_year.setdefault(year, {"finding": f})
        if any(w in label for w in _OBLIGATION):
            slot["prescribed_csr"] = value
        elif any(w in label for w in _SPENT):
            slot["total_spent"] = value

    out = []
    for year, slot in by_year.items():
        if "prescribed_csr" not in slot and "total_spent" not in slot:
            continue
        try:
            out.append(
                FunderCsrYearRecord(
                    funder_name=name,
                    fiscal_year=year,
                    prescribed_csr=slot.get("prescribed_csr"),
                    total_spent=slot.get("total_spent"),
                    as_of=year,
                    notes=f"Promoted from research: {slot['finding'].get('evidence', '')[:200]}",
                    **_provenance(slot["finding"], row["researched_at"]),
                )
            )
        except ValueError as exc:
            logger.info("csr year refused for %s %s: %s", row["slug"], year, exc)
    return out


async def promote(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Write what can be written from one research row. Returns a report."""
    findings = row["findings"] if isinstance(row["findings"], list) else []
    report: dict[str, Any] = {
        "slug": row["slug"], "funder": None, "csr_years": [], "skipped": {}, "reasons": []
    }
    for concept in sorted({f["concept"] for f in findings}):
        if concept not in PROMOTABLE:
            report["skipped"][concept] = len([f for f in findings if f["concept"] == concept])

    # An NGO is not a funder. Without this the first org researched becomes a
    # funders row, which is worse than not promoting it at all: it is a wrong
    # answer wearing a catalog citation.
    if row.get("entity_kind") == "org":
        report["reasons"].append(
            "researched as an organisation, not a funder. orgs has no writer yet "
            "(no OrgRecord, no resolve_org, no write_org), so this stays research. "
            "See docs/INGEST.md."
        )
        return report

    record = funder_from(row, findings)
    if record is None:
        report["reasons"].append("no identity or identifier finding to build a funder from")
        return report

    match = await resolve_funder(conn, record.name, record.identifiers)
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["reasons"].append(
            f"{record.name!r} resembles {names} without matching. Not merged — a person decides."
        )
        return report
    status, funder_id, _ = await write_funder(conn, record, match)
    report["funder"] = {"status": status, "id": funder_id, "name": record.name}

    for year_record in csr_years_from(row, findings):
        state, _ = await write_csr_year(conn, year_record, funder_id, None)
        report["csr_years"].append({"fiscal_year": year_record.fiscal_year, "status": state})
    return report


def now() -> datetime:
    return datetime.now(UTC)
