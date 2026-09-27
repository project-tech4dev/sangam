"""Does the agent's result answer what the gold SQL answers?"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from itertools import permutations
from typing import Any

NUMERIC_TOLERANCE = 1e-6
MAX_PROJECTION_WIDTH = 6
"""Above this, permutations explode; a gold that wide is a badly written case."""


def _normalize(value: Any) -> Any:
    """Numbers become floats so 700, 700.0, Decimal('700') and '700' all agree."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip()
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return text.lower()


def cells_equal(a: Any, b: Any) -> bool:
    a, b = _normalize(a), _normalize(b)
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= NUMERIC_TOLERANCE * max(1.0, abs(a), abs(b))
    if isinstance(a, str) and isinstance(b, str) and a != b:
        # Labels are presentation: a gold 'assam' matches an agent
        # 'assam (state)'. Requires >= 3 chars so 'a' does not match everything.
        shorter, longer = sorted((a, b), key=len)
        return len(shorter) >= 3 and shorter in longer
    return a == b


def _rows_as_tuples(rows: Sequence[Any]) -> list[tuple]:
    out = []
    for row in rows:
        out.append(tuple(row.values()) if isinstance(row, dict) else tuple(row))
    return out


def result_sets_match(gold: list[tuple], agent: list[tuple]) -> bool:
    """Multiset equality, order-insensitive, with per-cell tolerance."""
    if len(gold) != len(agent):
        return False
    remaining = list(agent)
    for gold_row in gold:
        for i, agent_row in enumerate(remaining):
            if len(gold_row) == len(agent_row) and all(
                cells_equal(x, y) for x, y in zip(gold_row, agent_row, strict=True)
            ):
                del remaining[i]
                break
        else:
            return False
    return True


def answer_contains_value(answer: str, value: Any) -> bool:
    """Is a value asserted in the narrated answer?"""
    text = (answer or "").lower()
    normalized = _normalize(value)
    if isinstance(normalized, float):
        whole = int(normalized)
        candidates = {str(normalized), f"{whole:,}", str(whole)}
        if normalized != whole:
            candidates.add(f"{normalized:,.2f}")
        return any(c.lower() in text for c in candidates)
    return str(normalized).lower() in text


def gold_satisfied(gold_rows: Sequence[Any], agent_rows: Sequence[Any], answer: str) -> bool:
    """Does the agent's result answer what the gold answers?"""
    gold = _rows_as_tuples(gold_rows)
    agent = _rows_as_tuples(agent_rows)
    if not gold:
        return not agent

    # Scalar gold (1 row x 1 column): the value must be supported by the result
    # AND stated in the answer, which is what carries the assertion to the user.
    if len(gold) == 1 and len(gold[0]) == 1:
        target = gold[0][0]
        supported = any(
            cells_equal(target, cell) for row in agent for cell in row
        ) or cells_equal(target, len(agent))  # "7 states" answered by 7 rows
        return supported and answer_contains_value(answer, target)

    # Single-row gold (a LIMIT 1 top/bottom question): agents often show the
    # full ranking and narrate the winner, so the gold row must merely appear.
    if len(gold) == 1:
        gold_row = gold[0]
        present = any(_row_contains(agent_row, gold_row) for agent_row in agent)
        labels = [c for c in gold_row if isinstance(_normalize(c), str)]
        return present and all(answer_contains_value(answer, lbl) for lbl in labels)

    # Otherwise: some selection of the agent's columns must equal the gold rows as a multiset. Extra COLUMNS
    # are fine (agents enrich); extra or missing ROWS are not.
    if agent and len(agent[0]) <= MAX_PROJECTION_WIDTH:
        width = len(gold[0])
        for picks in permutations(range(len(agent[0])), width):
            projected = [tuple(row[i] for i in picks) for row in agent]
            if result_sets_match(gold, projected):
                return True

    return _label_tolerant_match(gold, agent, answer)


def _row_contains(agent_row: tuple, gold_row: tuple) -> bool:
    remaining = list(agent_row)
    for cell in gold_row:
        for i, candidate in enumerate(remaining):
            if cells_equal(cell, candidate):
                del remaining[i]
                break
        else:
            return False
    return True


def _label_tolerant_match(gold: list[tuple], agent: list[tuple], answer: str) -> bool:
    """The agent invented its own category labels ('Oct-Dec 2025' for gold 'Q3')."""
    numeric_gold = [tuple(c for c in row if isinstance(_normalize(c), float)) for row in gold]
    labels = [c for row in gold for c in row if isinstance(_normalize(c), str)]
    if not labels or not all(numeric_gold):
        return False
    if len(set(numeric_gold)) != len(numeric_gold):
        return False
    if not all(answer_contains_value(answer, label) for label in labels):
        return False
    return gold_satisfied(numeric_gold, agent, answer)
