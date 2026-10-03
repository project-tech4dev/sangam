"""Resolve a name from a source to a row in the catalog, or to a person's queue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

Method = Literal["identifier", "exact", "alias", "boilerplate", "trigram", "none"]

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


def same_but_for_boilerplate(a: str, b: str) -> bool:
    """True when two names differ only by corporate boilerplate.

    'Axis Bank' and 'Axis Bank Limited' are one funder, and queueing them as a
    near-miss fragments its years across two rows. But a single-token core is
    not enough: 'Tata Trusts' and 'Tata Foundation' both reduce to 'tata' and
    are different organisations, so there the boilerplate is doing the work of
    telling them apart. Two tokens or more, and it is not.
    """
    tokens_a, tokens_b = core(a).split(), core(b).split()
    return tokens_a == tokens_b and len(tokens_a) >= 2


@dataclass(frozen=True, slots=True)
class Match:
    """One dataclass for both kinds. `entity_id` is a funders.id or an orgs.id
    depending on which resolver produced it, and the caller always knows which."""

    method: Method
    entity_id: int | None = None
    score: float | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """A trigram hit proposes; a person accepts. Everything else resolves."""
        return self.entity_id is not None


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

    # Same name plus "Limited" or "Trust" is the same funder, so it resolves
    # rather than waiting for a person. Only names that genuinely differ queue.
    rows = await (
        await conn.execute(
            "SELECT id, name FROM funders WHERE similarity(name, %s) >= %s",
            (name, TRIGRAM_FLOOR),
        )
    ).fetchall()
    for row in rows:
        if same_but_for_boilerplate(name, row["name"]):
            return Match("boilerplate", row["id"], 1.0)

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


async def resolve_org(conn: Any, name: str, identifiers: dict[str, str] | None = None) -> Match:
    """Three steps, not four: identifier, exact name, trigram.

    `resolve_funder` has an alias step reading `funder_identifiers` rows of
    id_type 'name'. org_identifiers' CHECK is pan|12a|80g|fcra|csr1|darpan|
    cin|reg_no, so there is no such row to read and no alias step to port.
    Everything else is the funder path: the same boilerplate rule, the same
    floors, the same trigram re-rank on the distinctive part of the name.
    """
    for id_type, id_value in (identifiers or {}).items():
        row = await (
            await conn.execute(
                "SELECT org_id FROM org_identifiers WHERE id_type = %s AND lower(id_value) = lower(%s)",
                (id_type, id_value),
            )
        ).fetchone()
        if row:
            return Match("identifier", row["org_id"])

    row = await (
        await conn.execute("SELECT id FROM orgs WHERE lower(name) = lower(%s)", (name,))
    ).fetchone()
    if row:
        return Match("exact", row["id"])

    rows = await (
        await conn.execute(
            "SELECT id, name FROM orgs WHERE similarity(name, %s) >= %s", (name, TRIGRAM_FLOOR)
        )
    ).fetchall()
    for row in rows:
        if same_but_for_boilerplate(name, row["name"]):
            return Match("boilerplate", row["id"], 1.0)

    rows = await (
        await conn.execute(
            "SELECT id, name, similarity(name, %s) AS score FROM orgs "
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
