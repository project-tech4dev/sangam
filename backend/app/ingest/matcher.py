"""Resolve a name from a source to a row in the catalog, or to a person's queue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

Method = Literal["identifier", "exact", "alias", "trigram", "none"]

# A wide net in SQL, then a strict re-rank on the distinctive part of the name.
TRIGRAM_FLOOR = 0.35
CORE_FLOOR = 0.62

# Words that almost every Indian corporate and philanthropic name carries. Left in,
# they dominate the score: "Bata India Limited" and "BASF India Limited" score 0.73
# against each other on the raw string, which is a near-miss for two unrelated firms.
NOISE = frozenset({
    "limited", "ltd", "private", "pvt", "plc", "inc", "llp", "company", "co", "corporation",
    "corp", "india", "indian", "bharat", "foundation", "foundations", "trust", "trusts",
    "charitable", "charities",
    "society", "sansthan", "samiti", "the", "and", "of", "for", "group", "holdings", "enterprises",
})


def core(name: str) -> str:
    """The distinctive part of a name: what is left after the boilerplate."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in NOISE]
    # Everything was boilerplate ("India Foundation"), so there is nothing to
    # distinguish on - fall back to the full name rather than matching on empty.
    return " ".join(tokens) if tokens else re.sub(r"[^a-z0-9 ]", " ", name.lower()).strip()


def core_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, core(a), core(b)).ratio()


@dataclass(frozen=True, slots=True)
class Match:
    method: Method
    funder_id: int | None = None
    score: float | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """Only steps 1 and 2 resolve. A trigram hit proposes; a person accepts."""
        return self.funder_id is not None


async def resolve_funder(conn: Any, name: str, identifiers: dict[str, str] | None = None) -> Match:
    """Four steps in order: identifier, exact name, alias, trigram."""
    for id_type, id_value in (identifiers or {}).items():
        row = await (
            await conn.execute(
                "SELECT funder_id FROM funder_identifiers WHERE id_type = %s AND lower(id_value) = lower(%s)",
                (id_type, id_value),
            )
        ).fetchone()
        if row:
            return Match("identifier", row["funder_id"])

    row = await (
        await conn.execute("SELECT id FROM funders WHERE lower(name) = lower(%s)", (name,))
    ).fetchone()
    if row:
        return Match("exact", row["id"])

    # funders has no aliases column; a known alternative spelling is stored as an
    # identifier of type 'name', which is what that id_type is for.
    row = await (
        await conn.execute(
            "SELECT funder_id FROM funder_identifiers WHERE id_type = 'name' AND lower(id_value) = lower(%s)",
            (name,),
        )
    ).fetchone()
    if row:
        return Match("alias", row["funder_id"])

    rows = await (
        await conn.execute(
            "SELECT id, name, similarity(name, %s) AS score FROM funders "
            "WHERE similarity(name, %s) >= %s ORDER BY score DESC LIMIT 10",
            (name, name, TRIGRAM_FLOOR),
        )
    ).fetchall()
    candidates = [
        {
            "id": r["id"],
            "name": r["name"],
            "score": round(core_similarity(name, r["name"]), 3),
            "raw_score": round(float(r["score"]), 3),
        }
        for r in rows
    ]
    survivors = sorted(
        (c for c in candidates if c["score"] >= CORE_FLOOR), key=lambda c: -c["score"]
    )[:3]
    if survivors:
        return Match("trigram", None, survivors[0]["score"], survivors)
    return Match("none")
