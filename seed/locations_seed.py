"""Seed every state and district in India from the Local Government Directory (LGD), idempotently.

Matches on `lgd_code`, then name or alias within the state, so code-less rows gain a code; never deletes.
"""

from __future__ import annotations

import csv
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field

import psycopg

GEOGRAPHY = pathlib.Path(__file__).parent / "data" / "geography"
COUNTRY = "India"
REGION = "Northeast India"


@dataclass
class District:
    state_code: str
    code: str
    name: str
    aliases: list[str] = field(default_factory=list)


def place_key(name: str) -> str:
    """Case and punctuation dropped, so 'Ri-Bhoi' and 'RI BHOI' are one place."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_rows() -> tuple[list[tuple[str, str]], list[District]]:
    with (GEOGRAPHY / "lgd_states.csv").open(encoding="utf-8") as f:
        states = [(r["lgd_code"], r["name"]) for r in csv.DictReader(f)]
    with (GEOGRAPHY / "lgd_districts.csv").open(encoding="utf-8") as f:
        districts = {r["lgd_code"]: District(r["state_lgd_code"], r["lgd_code"], r["name"])
                     for r in csv.DictReader(f)}
    with (GEOGRAPHY / "district_aliases.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            districts[r["lgd_code"]].aliases.append(r["alias"])
    return states, list(districts.values())


def _find(cur, kind: str, code: str, name: str, parent_id: int | None, aliases: list[str]) -> int | None:
    cur.execute("SELECT id FROM locations WHERE kind = %s AND lgd_code = %s", (kind, code))
    if row := cur.fetchone():
        return row[0]
    keys = [place_key(n) for n in (name, *aliases)]
    cur.execute(
        """
        SELECT id FROM locations
        WHERE kind = %s AND parent_id IS NOT DISTINCT FROM %s AND lgd_code IS NULL
          AND (regexp_replace(lower(name), '[^a-z0-9]', '', 'g') = ANY(%s)
               OR EXISTS (SELECT 1 FROM unnest(aliases) a
                          WHERE regexp_replace(lower(a), '[^a-z0-9]', '', 'g') = ANY(%s)))
        ORDER BY id LIMIT 1
        """,
        (kind, parent_id, keys, keys),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _put(cur, kind: str, code: str, name: str, parent_id: int, aliases: list[str]) -> int:
    found = _find(cur, kind, code, name, parent_id, aliases)
    if found is None:
        cur.execute(
            "INSERT INTO locations (kind, name, parent_id, lgd_code, aliases) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (kind, name, parent_id, code, aliases),
        )
        return cur.fetchone()[0]
    # Aliases are merged, so a spelling an earlier load recorded is kept.
    cur.execute(
        """
        UPDATE locations SET name = %s, lgd_code = %s, parent_id = %s,
               aliases = ARRAY(SELECT DISTINCT a FROM unnest(aliases || %s::text[]) a WHERE a <> %s ORDER BY a)
        WHERE id = %s
        """,
        (name, code, parent_id, aliases, name, found),
    )
    return found


def _root(cur, kind: str, name: str, parent_id: int | None) -> int:
    cur.execute(
        "SELECT id FROM locations WHERE kind = %s AND lower(name) = lower(%s) AND parent_id IS NOT DISTINCT FROM %s",
        (kind, name, parent_id),
    )
    if row := cur.fetchone():
        return row[0]
    cur.execute("INSERT INTO locations (kind, name, parent_id) VALUES (%s, %s, %s) RETURNING id",
                (kind, name, parent_id))
    return cur.fetchone()[0]


def seed_locations(cur) -> dict[str, int]:
    states, districts = read_rows()
    india = _root(cur, "country", COUNTRY, None)
    # A label only: the eight states stay under India, where Import looks them up.
    _root(cur, "region", REGION, india)
    state_ids = {code: _put(cur, "state", code, name, india, []) for code, name in states}
    for d in districts:
        _put(cur, "district", d.code, d.name, state_ids[d.state_code], d.aliases)
    return {"states": len(state_ids), "districts": len(districts)}


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        counts = seed_locations(cur)
        conn.commit()
    print(f"seeded: {counts['states']} states and union territories, {counts['districts']} districts (LGD)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
