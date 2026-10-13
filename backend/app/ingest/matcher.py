"""Resolve a name from a source to a row in the catalog, or to a person's queue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from app.ingest.records import normalise_cin

Method = Literal["identifier", "exact", "alias", "boilerplate", "website", "trigram", "none"]

# A wide net in SQL, then a strict re-rank on the distinctive part of the name.
TRIGRAM_FLOOR = 0.35
# A state society's registration number ('26', '320/2000') repeats across registrars: never an identity.
UNMATCHABLE_ID_TYPES = frozenset({"reg_no"})
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


def close_names(a: str, b: str) -> bool:
    """Worth asking a person: the distinctive part is close and every number agrees.
    "Keystone Foundation" is not close to "Anudip Foundation"; "Mission 2 Million" is not "Mission 1 Million"."""
    return re.findall(r"\d+", a) == re.findall(r"\d+", b) and core_similarity(a, b) >= CORE_FLOOR


def name_key(name: str) -> str:
    """One spelling per CSO name, for comparison only: folds North East/North-East/Northeast, drops 'The' and
    punctuation, keeps bracket content ('Example Trust (North)' and '(South)' are two chapters)."""
    folded = re.sub(r"north[\s\-]*east", "northeast", name.lower())
    return " ".join(t for t in re.findall(r"[a-z0-9]+", folded) if t != "the")


_PAREN = re.compile(r"^(.*\S)\s*\(([^)]*)\)\s*$")


def variants(name: str) -> list[str]:
    """Other spellings a name carries: without its parenthetical, and the parenthetical when it is a name.
    "Knowledge and Advocacy for Better Livelihoods (KABIL)" -> the long name, and "KABIL"."""
    m = _PAREN.match(name)
    if not m:
        return []
    inner = m[2].strip()
    return [m[1].strip(), *([inner] if re.search(r"[A-Za-z]{2}", inner) else [])]


def domain(url: str | None) -> str | None:
    m = re.match(r"^(?:[a-z]+://)?(?:www\.)?([^/:?#]+)", (url or "").strip().lower())
    return m[1] if m and "." in m[1] else None


_DOMAIN_SQL = r"lower(substring(website from '^(?:[A-Za-z]+://)?(?:www\.)?([^/:?#]+)'))"


async def _one(conn: Any, table: str, spelling: str) -> int | None:
    """The one row whose name or alias is this spelling; None for none or two."""
    rows = await (
        await conn.execute(
            f"SELECT id FROM {table} WHERE lower(name) = lower(%s) OR EXISTS "
            "(SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(%s)) ORDER BY id LIMIT 2",
            (spelling, spelling),
        )
    ).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


async def _by_website(conn: Any, table: str, website: str | None) -> list[dict[str, Any]]:
    host = domain(website)
    if not host:
        return []
    return await (
        await conn.execute(
            f"SELECT id, name, aliases FROM {table} WHERE {_DOMAIN_SQL} = %s ORDER BY id LIMIT 2", (host,)
        )
    ).fetchall()


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


# Words that make a name a foundation or trust rather than the company itself.
_FOUNDATION_WORDS = frozenset({
    "foundation", "foundations", "trust", "trusts", "charitable", "charities", "society",
    "sansthan", "samiti",
})


def _is_foundation(name: str) -> bool:
    return bool(set(re.findall(r"[a-z0-9]+", name.lower())) & _FOUNDATION_WORDS)


def _same_organisation(name: str, held: str, aliases: list[str]) -> bool:
    """Same distinctive name; two foundations need a multi-token core ('Tata Trusts' is not 'Tata Foundation')."""
    def same(n: str) -> bool:
        if n.lower() == name.lower():
            return True
        if _is_foundation(name) != _is_foundation(n):
            return False
        if _is_foundation(name):
            return same_but_for_boilerplate(name, n)
        return core(name) == core(n)

    return any(same(n) for n in (held, *aliases))


async def resolve_funder(conn: Any, name: str, cin: str | None = None, website: str | None = None) -> Match:
    """In order: CIN, exact name, alias, the name's variants, website domain, boilerplate, trigram.

    A CIN hit must also look like the same organisation: filings attach to the parent (D7), so a
    foundation's research often carries its parent's CIN. Such a hit falls through to the name steps.
    """
    if cin:
        row = await (
            await conn.execute(
                "SELECT id, name, aliases FROM funders WHERE cin = %s", (normalise_cin(cin),)
            )
        ).fetchone()
        if row and _same_organisation(name, row["name"], row["aliases"] or []):
            return Match("identifier", row["id"])

    row = await (
        await conn.execute("SELECT id FROM funders WHERE lower(name) = lower(%s)", (name,))
    ).fetchone()
    if row:
        return Match("exact", row["id"])

    # One funder per spelling. Two rows sharing an alias is a case a person settles.
    rows = await (
        await conn.execute(
            "SELECT id FROM funders WHERE EXISTS "
            "(SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(%s)) ORDER BY id LIMIT 2",
            (name,),
        )
    ).fetchall()
    if len(rows) == 1:
        return Match("alias", rows[0]["id"])
    for spelling in variants(name):
        if (found := await _one(conn, "funders", spelling)) is not None:
            return Match("alias", found)
    # A company and its foundation can share a site, so the domain must also name the same organisation.
    hits = await _by_website(conn, "funders", website)
    if len(hits) == 1 and _same_organisation(name, hits[0]["name"], hits[0]["aliases"] or []):
        return Match("website", hits[0]["id"])

    # Same name plus "Limited" or "Trust" is the same funder, so it resolves
    # rather than waiting for a person. Only names that genuinely differ queue.
    rows = await (
        await conn.execute(
            "SELECT id, name FROM funders WHERE similarity(name, %s) >= %s",
            (name, TRIGRAM_FLOOR),
        )
    ).fetchall()
    for row in rows:
        if same_but_for_boilerplate(name, row["name"]) and _is_foundation(name) == _is_foundation(
            row["name"]
        ):
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


async def resolve_org(
    conn: Any, name: str, identifiers: dict[str, str] | None = None, website: str | None = None
) -> Match:
    """Identifier, exact name, alias, the name's variants, website domain, normalised name or alias, boilerplate,
    then trigram.
    A spelling two organisations share resolves neither and falls through to trigram, which only proposes."""
    for id_type, id_value in (identifiers or {}).items():
        if id_type in UNMATCHABLE_ID_TYPES:
            continue
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
            "SELECT id FROM orgs WHERE EXISTS "
            "(SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(%s)) ORDER BY id LIMIT 2",
            (name,),
        )
    ).fetchall()
    if len(rows) == 1:
        return Match("alias", rows[0]["id"])
    for spelling in variants(name):
        if (found := await _one(conn, "orgs", spelling)) is not None:
            return Match("alias", found)
    hits = await _by_website(conn, "orgs", website)
    if len(hits) == 1:
        return Match("website", hits[0]["id"])

    rows = await (
        await conn.execute(
            "SELECT id, name, aliases FROM orgs WHERE similarity(name, %s) >= %s "
            "OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE similarity(a, %s) >= %s)",
            (name, TRIGRAM_FLOOR, name, TRIGRAM_FLOOR),
        )
    ).fetchall()
    key = name_key(name)
    same = {r["id"] for r in rows if key in {name_key(n) for n in (r["name"], *(r.get("aliases") or []))}}
    if len(same) == 1:
        return Match("alias", same.pop())
    if not same:
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
