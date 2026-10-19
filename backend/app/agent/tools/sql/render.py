"""Render query rows for the model: compact, cited, and honest about truncation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.agent.tools.sql.validator import CitationPlan, ProvenancePlan

MAX_CELL_CHARS = 200
MAX_OUTPUT_CHARS = 6_000
# A single row is what the model asked to read in full, like an org's description; one row may run to twice the budget.
ONE_ROW_CELL_CHARS = 2_000

# Distinct sources named per query. The block is deduped and budgeted separately from the
# rows, so adding provenance never costs the model a row of data.
MAX_SOURCES = 8
MAX_SOURCE_NAME_CHARS = 60

NO_ROWS = (
    "The query ran and matched nothing. For these filters that is a real "
    "'no data' answer — say so rather than retrying with looser filters, unless "
    "you think a filter value was wrong (use db_profile_column to check how the "
    "values are actually stored)."
)


def render_cell(value: Any, max_chars: int = MAX_CELL_CHARS) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
    elif isinstance(value, Decimal):
        text = format(value.normalize(), "f")
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, separators=(",", ":"), default=str)
    else:
        text = str(value)
    if len(text) > max_chars:
        return f"{text[: max_chars - 1]}… ({len(text)} chars total)"
    return text


def render_rows(
    rows: Sequence[dict[str, Any]],
    *,
    citations: Sequence[CitationPlan] = (),
    provenance: Sequence[ProvenancePlan] = (),
    limit: int | None = None,
    truncated: bool = False,
) -> str:
    """Rows as a pipe-separated block, each prefixed with its citation markers."""
    if not rows:
        return NO_ROWS

    plans = [p for p in citations if p.output_column in rows[0]]
    cited_columns = {p.output_column for p in plans}
    # Source columns are reported once in the sources block, not repeated on every row —
    # including one the model selected itself, which is why this covers more than the
    # aliases the validator appended.
    source_columns = {p.output_column for p in provenance if p.output_column in rows[0]}
    body_columns = [c for c in rows[0] if c not in cited_columns and c not in source_columns]

    lines: list[str] = []
    if body_columns:
        lines.append("columns: " + " | ".join(body_columns))
    elif plans:
        lines.append("columns: (identifiers only)")

    def line_of(row: dict[str, Any], max_chars: int) -> str:
        markers = dict.fromkeys(
            f"[{p.kind}:{row[p.output_column]}] " for p in plans if row.get(p.output_column) is not None
        )
        body = " | ".join(render_cell(row.get(c), max_chars) for c in body_columns)
        return f"{''.join(markers)}{body}".rstrip()

    if len(rows) == 1 and len(wide := line_of(rows[0], ONE_ROW_CELL_CHARS)) <= 2 * MAX_OUTPUT_CHARS:
        lines.append(wide)
        rows = []

    shown = 0
    budget = MAX_OUTPUT_CHARS
    for row in rows:
        line = line_of(row, MAX_CELL_CHARS)
        if budget - len(line) < 0:
            break
        budget -= len(line) + 1
        lines.append(line)
        shown += 1

    if shown < len(rows):
        lines.append(
            f"… {len(rows) - shown} more row(s) not shown (output budget reached). "
            "Aggregate, or narrow the WHERE clause."
        )
    if truncated and limit is not None:
        lines.append(
            f"Rows shown: {limit} of {limit}+ — the LIMIT truncated the result, so this is "
            "NOT a complete picture. Do not present these figures as totals."
        )
    if not plans:
        lines.append(
            "These rows carry no citation markers: the query aggregates or combines rows, or reads "
            "no table with an id to cite. If the answer names specific rows, query them plainly."
        )
    return "\n".join(lines)


def render_caveats(defects: Sequence[str]) -> str:
    """Known data problems for the tables a query touched."""
    if not defects:
        return ""
    return "caveats: " + " ".join(defects)


def render_repeat_caveats(tables: Sequence[str]) -> str:
    """Tables whose caveats an earlier result this turn gave in full; the part that changes an answer stays."""
    if not tables:
        return ""
    return (
        f"caveats: {', '.join(tables)}: as given earlier this turn. Rows here are only what this user "
        "can see; 0 rows is not 'none exist'."
    )


def _as_day(value: Any) -> str:
    """A fetch date, day precision — the hour is noise in a source line."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if isinstance(value, date) else ""


def render_sources(
    rows: Sequence[dict[str, Any]],
    *,
    provenance: Sequence[ProvenancePlan],
    skipped: str | None = None,
) -> str:
    """Where the rows came from: one line per distinct source, deduped across rows.

    The grammar is a contract — the Ask workspace parses it to build its Sources list.
    `frontend/features/ask/lib/sources.ts` reads it, and
    `tests/test_sql_render.py::TestSources::test_the_line_grammar_is_a_contract` pins it.
    """
    if not rows or not provenance:
        return f"sources: none — {skipped}" if skipped else ""

    by_table: dict[str, dict[str, str]] = {}
    for plan in provenance:
        by_table.setdefault(plan.table, {})[plan.role] = plan.output_column

    seen: set[tuple[str, str, str, str]] = set()
    lines: list[str] = []
    for row in rows:
        for table, roles in by_table.items():
            url = row.get(roles.get("url", ""))
            if not url:
                continue
            name = row.get(roles.get("name", "")) or ""
            fetched = row.get(roles.get("fetched", ""))
            entry = (table, str(url), str(name)[:MAX_SOURCE_NAME_CHARS], _as_day(fetched))
            if entry in seen:
                continue
            seen.add(entry)
            # The URL is never passed through render_cell: a truncated link is a dead link.
            lines.append("  " + " · ".join(part for part in entry if part))
            if len(lines) == MAX_SOURCES:
                break
        if len(lines) == MAX_SOURCES:
            break

    if not lines:
        return "sources: none recorded for these rows — the source columns are empty"
    header = f"sources: {len(lines)}" + (f" of {MAX_SOURCES}+ shown" if len(lines) == MAX_SOURCES else "")
    return "\n".join([header, *lines])
