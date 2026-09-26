"""Render query rows for the model: compact, cited, and honest about truncation.

Two budgets, because they fail differently. A single 40 KB JSONB cell blows the
context window on one row, so cells are capped individually; fifty ordinary rows
also blow it, so the whole block is capped too. Exceeding either is reported —
an LLM handed a silently truncated top-50 will report it as the whole table.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.agent.tools.sql.validator import CitationPlan

MAX_CELL_CHARS = 200
MAX_OUTPUT_CHARS = 6_000

NO_ROWS = (
    "The query ran and matched nothing. For these filters that is a real "
    "'no data' answer — say so rather than retrying with looser filters, unless "
    "you think a filter value was wrong (use db_profile_column to check how the "
    "values are actually stored)."
)


def render_cell(value: Any) -> str:
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
    if len(text) > MAX_CELL_CHARS:
        return f"{text[: MAX_CELL_CHARS - 1]}… ({len(text)} chars total)"
    return text


def render_rows(
    rows: Sequence[dict[str, Any]],
    *,
    citations: Sequence[CitationPlan] = (),
    limit: int | None = None,
    truncated: bool = False,
) -> str:
    """Rows as a pipe-separated block, each prefixed with its citation markers.

    The columns that produced a marker are not repeated in the row body — the
    marker already carries the value, and repeating it wastes context on every row.
    """
    if not rows:
        return NO_ROWS

    plans = [p for p in citations if p.output_column in rows[0]]
    cited_columns = {p.output_column for p in plans}
    body_columns = [c for c in rows[0] if c not in cited_columns]

    lines: list[str] = []
    if body_columns:
        lines.append("columns: " + " | ".join(body_columns))
    elif plans:
        lines.append("columns: (identifiers only)")

    shown = 0
    budget = MAX_OUTPUT_CHARS
    for row in rows:
        markers = "".join(
            f"[{p.kind}:{row[p.output_column]}] " for p in plans if row.get(p.output_column) is not None
        )
        body = " | ".join(render_cell(row.get(c)) for c in body_columns)
        line = f"{markers}{body}".rstrip()
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
            "No citable id column was projected, so these rows carry no citation markers. "
            "Add the table's id column (e.g. orgs.id) to the SELECT list if the answer needs "
            "to cite specific rows."
        )
    return "\n".join(lines)


def render_caveats(defects: Sequence[str]) -> str:
    """Known data problems for the tables a query touched."""
    if not defects:
        return ""
    return "caveats: " + " ".join(defects)
