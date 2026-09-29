"""Move research findings into the catalog, where a writer exists for them.

Research and catalog are different things. A finding is what a source said,
with the sentence that says it; a catalog row is a fact the product answers
questions from. This is the deliberate step between them, and it only moves
what there is somewhere to move — the rest is reported, not silently dropped.

Findings arrive typed (app/ingest/research_records.py), so this file maps
fields to columns. It does not parse: the last version read free text with
regular expressions and refused a real figure because it could not tell crore
from rupees, which is the good half of that failure mode.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.ingest.matcher import resolve_funder
from app.ingest.records import FunderCsrYearRecord, FunderRecord
from app.ingest.research_records import SCHEMA_VERSION
from app.ingest.writer import write_csr_year, write_funder

logger = logging.getLogger(__name__)

# identity/identifier → funders, csr_year → funder_csr_years. Everything else
# has no writer yet: see docs/INGEST.md.
PROMOTABLE = ("identity", "identifier", "csr_year")


def _inr(money: dict[str, Any] | None) -> float | None:
    """A Money finding as INR. The conversion lives in Money.inr; this is its
    dict form, because findings come back out of jsonb."""
    if not money:
        return None
    units = {"inr": 1, "lakh": 1_00_000, "crore": 1_00_00_000}
    unit = money.get("unit")
    if unit not in units:
        return None
    return float(money["value"]) * units[unit]


def _provenance(finding: dict[str, Any], fetched: datetime) -> dict[str, Any]:
    return {
        "source_url": finding["source_url"],
        "source_name": finding.get("source_name") or "research",
        "fetched_at": fetched,
    }


def funder_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> FunderRecord | None:
    """One funder record, from the identity finding and any identifiers."""
    identity = next((f for f in findings if f["concept"] == "identity"), None)
    identifiers = [f for f in findings if f["concept"] == "identifier"]
    anchor = identity or (identifiers[0] if identifiers else None)
    if anchor is None:
        return None
    try:
        return FunderRecord(
            name=(identity or {}).get("name") or row["canonical_name"] or row["entity_name"],
            funder_type=(identity or {}).get("funder_type"),
            website=(identity or {}).get("website") or row.get("website"),
            identifiers={f["id_type"]: f["id_value"] for f in identifiers},
            as_of=None,
            **_provenance(anchor, row["researched_at"]),
        )
    except ValueError as exc:
        logger.info("funder record refused for %s: %s", row["slug"], exc)
        return None


def csr_years_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> list[FunderCsrYearRecord]:
    """One record per fiscal year. Each finding already names its own columns."""
    name = row["canonical_name"] or row["entity_name"]
    out = []
    for f in findings:
        if f["concept"] != "csr_year":
            continue
        try:
            out.append(
                FunderCsrYearRecord(
                    funder_name=name,
                    fiscal_year=f["fiscal_year"],
                    prescribed_csr=_inr(f.get("prescribed_csr")),
                    total_spent=_inr(f.get("total_spent")),
                    average_net_profit=_inr(f.get("average_net_profit")),
                    unspent_transferred=_inr(f.get("unspent_transferred")),
                    section_135_applicable=f.get("section_135_applicable"),
                    notes=f.get("notes") or f"Promoted from research: {f.get('evidence', '')[:200]}",
                    as_of=f["fiscal_year"],
                    **_provenance(f, row["researched_at"]),
                )
            )
        except ValueError as exc:
            logger.info("csr year refused for %s %s: %s", row["slug"], f.get("fiscal_year"), exc)
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

    # Flat label/value findings cannot be mapped to columns without the
    # guessing this file was rewritten to remove. Re-research, do not migrate.
    if findings and row.get("schema_version", 1) < SCHEMA_VERSION:
        report["reasons"].append(
            f"researched under finding shape v{row.get('schema_version', 1)}, which has no typed "
            f"fields to map. Re-run the research for {row['slug']} and promote that."
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
