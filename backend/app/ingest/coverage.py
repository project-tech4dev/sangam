"""Expected vs pulled for one saved research row: concepts by year, fields, and why each gap is a gap.

Pure: no pool, no async. The supervisor prints `render()` verbatim, so the numbers are never the model's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ingest.expectations import CONCEPTS, concepts_for, expected_fields, recent_fiscal_years
from app.ingest.research_records import YEARLY

_FY = re.compile(r"FY\d{4}-\d{2}")

REASONS = ("not_attempted", "not_stated", "blocked", "not_written")
LABELS = {"not_attempted": "not attempted", "not_stated": "not stated", "blocked": "blocked",
          "not_written": "found, not written"}


@dataclass
class Cell:
    concept: str
    year: str | None
    status: str  # "found" or one of REASONS
    detail: str = ""


@dataclass
class ConceptLine:
    concept: str
    cells: list[Cell]
    fields_filled: int
    fields_total: int
    held: int = 0
    extra_years: list[str] = field(default_factory=list)
    untagged: list[str] = field(default_factory=list)  # programme names saved with no theme
    programmes: int = 0


@dataclass
class Coverage:
    entity: str
    kind: str
    years: list[str]
    lines: list[ConceptLine]
    write_checked: bool

    @property
    def cells(self) -> list[Cell]:
        return [c for line in self.lines for c in line.cells]


def _filled(value: Any) -> bool:
    return value not in (None, "", [], {})


def _gap_for(gaps: list[dict[str, Any]], concept: str, year: str | None) -> dict[str, Any] | None:
    # A field-level gap describes a found concept, so it never explains a missing cell.
    for g in gaps:
        if g.get("concept") == concept and not g.get("field") and g.get("fiscal_year") in (year, None):
            return g
    return None


def _held_count(held: list[str], concept: str) -> int:
    return sum(1 for h in held if h.split(" ", 1)[0].rstrip(":") == concept)


def compute(row: dict[str, Any], years: list[str] | None = None,
            report: dict[str, Any] | None = None) -> Coverage:
    """`row` is an entity_research row; `report` a dry-run promote() report, funders only."""
    kind = row.get("entity_kind") or "unknown"
    findings = row.get("findings") if isinstance(row.get("findings"), list) else []
    gaps = row.get("gaps") if isinstance(row.get("gaps"), list) else []
    # A row saved before `years` existed still names them in its goals.
    asked = years or row.get("years") or sorted(set(_FY.findall(" ".join(map(str, row.get("goals") or [])))))
    years = sorted(asked or recent_fiscal_years(), reverse=True)
    if not gaps and row.get("not_found"):
        gaps = [{"concept": c, "reason": "not_stated", "detail": ""} for c in row["not_found"]]
    skipped = (report or {}).get("skipped", {})
    held = (report or {}).get("held", [])
    concepts = concepts_for(kind) if kind != "unknown" else tuple(CONCEPTS)

    lines: list[ConceptLine] = []
    for concept in concepts:
        mine = [f for f in findings if f.get("concept") == concept]
        cells: list[Cell] = []
        for year in (years if concept in YEARLY else [None]):
            hits = [f for f in mine if year is None or f.get("fiscal_year") == year]
            if hits:
                status = "not_written" if concept in skipped else "found"
                cells.append(Cell(concept, year, status, "no catalog writer" if status == "not_written" else ""))
                continue
            gap = _gap_for(gaps, concept, year)
            if gap:
                # A run that stopped before looking has not attempted it, and says what was left unread.
                status = "not_attempted" if gap["reason"] == "not_reached" else gap["reason"]
                cells.append(Cell(concept, year, status, gap.get("detail", "")))
            else:
                cells.append(Cell(concept, year, "not_attempted"))
        expected = [e.name for e in expected_fields(concept)]
        filled = sum(1 for name in expected if any(_filled(f.get(name)) for f in mine))
        extra = sorted({f["fiscal_year"] for f in mine
                        if concept in YEARLY and f.get("fiscal_year") and f["fiscal_year"] not in years})
        untagged = [f.get("name") or "?" for f in mine if concept == "program" and not f.get("themes")]
        lines.append(ConceptLine(concept, cells, filled, len(expected), _held_count(held, concept), extra,
                                 untagged, len(mine) if concept == "program" else 0))
    return Coverage(row.get("canonical_name") or row.get("entity_name") or row.get("slug", "?"),
                    kind, years, lines, report is not None)


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "–"


def _missing_text(line: ConceptLine) -> str:
    parts: list[str] = []
    for reason in REASONS:
        cells = [c for c in line.cells if c.status == reason]
        if not cells:
            continue
        years = ", ".join(c.year for c in cells if c.year)
        detail = next((c.detail for c in cells if c.detail), "")
        parts.append(" ".join(p for p in (years, LABELS[reason]) if p) + (f": {detail}" if detail else ""))
    if line.held:
        parts.append(f"{line.held} line(s) held back at the write")
    if line.extra_years:
        parts.append(f"also found {', '.join(line.extra_years)} (not asked)")
    if line.untagged:
        parts.append(f"{len(line.untagged)} of {line.programmes} programmes have no theme: {', '.join(line.untagged)}")
    return "; ".join(parts) or "–"


def render(cov: Coverage) -> str:
    cells = cov.cells
    total, found = len(cells), sum(1 for c in cells if c.status == "found")
    missing = total - found
    f_filled = sum(line.fields_filled for line in cov.lines)
    f_total = sum(line.fields_total for line in cov.lines)
    by_reason = " · ".join(
        f"{LABELS[r]} {n} ({_pct(n, total)})" for r in REASONS if (n := sum(1 for c in cells if c.status == r))
    ) or "nothing"
    span = f"{cov.years[-1]} to {cov.years[0]}" if len(cov.years) > 1 else (cov.years[0] if cov.years else "")
    out = [
        f"Coverage: {cov.entity} ({cov.kind}), {span}",
        f"Concepts {found}/{total} ({_pct(found, total)}) · Fields {f_filled}/{f_total} ({_pct(f_filled, f_total)})",
        f"Missing {missing} ({_pct(missing, total)}): {by_reason}",
        "",
        f"{'concept':<22}{'years':<7}{'fields':<8}missing",
    ]
    for line in cov.lines:
        hit = sum(1 for c in line.cells if c.status == "found")
        years = f"{hit}/{len(line.cells)}" if line.cells[0].year else ("✓" if hit else "–")
        out.append(f"{line.concept:<22}{years:<7}{f'{line.fields_filled}/{line.fields_total}':<8}"
                   f"{_missing_text(line)}")
    if not cov.write_checked:
        out.append("\n'Found, not written' is not checked for an NGO: its write cannot be dry-run.")
    return "\n".join(out)


def _written_label(concept: str) -> str:
    spec = CONCEPTS[concept]
    return spec.table + (f" ({spec.row_filter[1]})" if spec.row_filter else "")


# promote() counts rows under these labels (`_count`); each names one concept.
CONCEPT_OF_WRITTEN = {_written_label(c): c for c in CONCEPTS if c not in ("identity", "org_identity", "csr_year")}


def changes_by_concept(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Rows a promote() report added and updated, per concept. Works on a real write and on a plan."""
    out: dict[str, dict[str, int]] = {}

    def bump(concept: str, status: str, n: int = 1) -> None:
        if status in ("added", "updated"):
            out.setdefault(concept, {"added": 0, "updated": 0})[status] += n

    entity = report.get("entity") or {}
    if entity:
        bump("org_identity" if entity.get("kind") == "org" else "identity", entity.get("status", ""))
    for year in report.get("csr_years", []):
        bump("csr_year", year.get("status", ""))
    for label, counts in (report.get("written") or {}).items():
        concept = CONCEPT_OF_WRITTEN.get(label)
        if concept:
            for status, n in counts.items():
                bump(concept, status, n)
    return out


def as_dict(cov: Coverage) -> dict[str, Any]:
    """`compute()` as JSON for the Import screen; `render()` stays the agent's text."""
    cells = cov.cells
    return {
        "name": cov.entity, "kind": cov.kind, "years": cov.years, "write_checked": cov.write_checked,
        "cells": len(cells), "found": sum(1 for c in cells if c.status == "found"),
        "fields_filled": sum(line.fields_filled for line in cov.lines),
        "fields_total": sum(line.fields_total for line in cov.lines),
        "concepts": [
            {"concept": line.concept, "title": CONCEPTS[line.concept].title,
             "cells": [{"year": c.year, "status": c.status, "detail": c.detail} for c in line.cells],
             "fields_filled": line.fields_filled, "fields_total": line.fields_total,
             "held": line.held, "extra_years": line.extra_years}
            for line in cov.lines
        ],
    }


def saved_record(prior: dict[str, Any] | None, report: dict[str, Any],
                 rows_after: dict[str, int] | None) -> dict[str, Any] | None:
    """What to store on the research row after a save, or None to keep the stored one.
    A re-save that writes nothing would read before == after; one that writes more keeps the first before."""
    changes = changes_by_concept(report)
    if prior and not changes:
        return None
    if not prior and not report.get("entity"):
        return None  # refused before anything was written: research stays unsaved
    if prior:
        for concept, counts in (prior.get("changes") or {}).items():
            mine = changes.setdefault(concept, {"added": 0, "updated": 0})
            for status, n in counts.items():
                mine[status] = mine.get(status, 0) + n
    rows_before = (prior or {}).get("rows_before")
    if rows_before is None and rows_after is not None:
        rows_before = {c: max(n - changes.get(c, {}).get("added", 0), 0) for c, n in rows_after.items()}
    return {
        "entity": report.get("entity"), "changes": changes,
        "rows_before": rows_before, "rows_after": rows_after,
        "held": report.get("held", []), "skipped": dict(report.get("skipped", {})),
        "reasons": report.get("reasons", []), "conflicts": report.get("conflicts", []),
    }


def view(row: dict[str, Any], *, stage: str, report: dict[str, Any] | None, entity: dict[str, Any] | None,
         reasons: list[str], held: list[str], questions: int, changes: dict[str, dict[str, int]],
         before: dict[str, int] | None, after: dict[str, int] | None) -> dict[str, Any]:
    """The coverage endpoint's body, once the stage's numbers are in hand."""
    cov = as_dict(compute(row, report=report))
    for line in cov["concepts"]:
        c = line["concept"]
        line.update(changes.get(c, {"added": 0, "updated": 0}))
        line["before"] = before.get(c) if before is not None else None
        line["after"] = after.get(c) if after is not None else None
    return {
        "slug": row["slug"], "stage": stage, "saved_at": row.get("saved_at"),
        "entity": entity, "reasons": reasons, "held": held, "questions": questions,
        "facts_before": sum(before.values()) if before is not None else None,
        "facts_after": sum(after.values()) if after is not None else None,
        **cov,
    }
