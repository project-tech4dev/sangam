"""Resolving a place name from a report to a row in `locations`.

Both lists are closed: `seed.locations_seed` loads LGD's 36 states and 784 districts, so a
place that is not there is refused with the reason, never created — a typo would be a place for good.
"""

from __future__ import annotations

import re
from typing import Any

# The 28 states and 8 union territories. Canonical spelling on the left; the
# right is what sources actually print, including names changed years ago that
# annual reports still use.
_STATES: dict[str, tuple[str, ...]] = {
    "Andhra Pradesh": ("ap",),
    "Arunachal Pradesh": (),
    "Assam": (),
    "Bihar": (),
    "Chhattisgarh": ("chattisgarh",),
    "Goa": (),
    "Gujarat": (),
    "Haryana": (),
    "Himachal Pradesh": ("hp",),
    "Jharkhand": (),
    "Karnataka": (),
    "Kerala": (),
    "Madhya Pradesh": ("mp",),
    "Maharashtra": (),
    "Manipur": (),
    "Meghalaya": (),
    "Mizoram": (),
    "Nagaland": (),
    "Odisha": ("orissa",),
    "Punjab": (),
    "Rajasthan": (),
    "Sikkim": (),
    "Tamil Nadu": ("tamilnadu", "tn"),
    "Telangana": (),
    "Tripura": (),
    "Uttar Pradesh": ("up",),
    "Uttarakhand": ("uttaranchal",),
    "West Bengal": ("wb",),
    "Andaman and Nicobar Islands": ("andaman & nicobar islands", "andaman and nicobar",
                                    "andaman & nicobar"),
    "Chandigarh": (),
    "Dadra and Nagar Haveli and Daman and Diu": ("dadra & nagar haveli and daman & diu",
                                                 "dadra and nagar haveli", "daman and diu"),
    "Delhi": ("nct of delhi", "new delhi", "national capital territory of delhi"),
    "Jammu and Kashmir": ("jammu & kashmir", "j&k"),
    "Ladakh": (),
    "Lakshadweep": (),
    "Puducherry": ("pondicherry",),
}

_BY_NAME: dict[str, str] = {}
for _canonical, _aliases in _STATES.items():
    _BY_NAME[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _BY_NAME[_alias] = _canonical

COUNTRY = "India"


def canonical_state(name: str) -> str | None:
    """One spelling per state, or None when the name is not one."""
    key = name.strip().lower().replace(" state", "").replace("&", "and")
    key = " ".join(key.split())
    return _BY_NAME.get(key)


async def _ensure(conn: Any, kind: str, name: str, parent_id: int | None) -> int:
    """Find this country or state, or create it; the state was already checked against the closed list."""
    row = await (
        await conn.execute(
            "SELECT id FROM locations WHERE kind = %s AND lower(name) = lower(%s) "
            "AND parent_id IS NOT DISTINCT FROM %s",
            (kind, name, parent_id),
        )
    ).fetchone()
    if row:
        return row["id"]
    row = await (
        await conn.execute(
            "INSERT INTO locations (kind, name, parent_id) VALUES (%s, %s, %s) RETURNING id",
            (kind, name, parent_id),
        )
    ).fetchone()
    return row["id"]


async def resolve_location(
    conn: Any, state: str | None, district: str | None = None
) -> tuple[int | None, str | None]:
    """The locations row for a place, or why there is none.

    Returns (id, None) or (None, reason). The reason is reported to the user
    rather than logged, because a footprint that cannot be placed is a fact we
    chose not to store and somebody should know which one.
    """
    if not state:
        if district:
            return None, (
                f"{district!r} has no state, and a district on its own cannot be resolved — "
                f"several states have a Bishnupur"
            )
        return None, "no place given"

    canonical = canonical_state(state)
    if canonical is None:
        return None, (
            f"{state!r} is not one of India's 28 states or 8 union territories. Not created — "
            f"a misspelling that becomes a state row is wrong for good"
        )

    country_id = await _ensure(conn, "country", COUNTRY, None)
    state_id = await _ensure(conn, "state", canonical, country_id)
    if not district:
        return state_id, None
    return await _district(conn, district, canonical, state_id)


def district_key(name: str) -> str:
    """Case, punctuation and a trailing 'district' dropped, so 'Ri-Bhoi District' is RI BHOI."""
    key = re.sub(r"\s+(district|dist\.?)$", "", name.strip().lower())
    return re.sub(r"[^a-z0-9]", "", key)


_KEY = "regexp_replace(lower({}), '[^a-z0-9]', '', 'g')"


async def _district(conn: Any, district: str, state: str, state_id: int) -> tuple[int | None, str | None]:
    """A district of this state by name, then by alias; an official name wins over another's alias."""
    key = district_key(district)
    row = await (
        await conn.execute(
            f"SELECT id FROM locations WHERE kind = 'district' AND parent_id = %s "
            f"AND ({_KEY.format('name')} = %s OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE {_KEY.format('a')} = %s)) "
            f"ORDER BY {_KEY.format('name')} = %s DESC, id LIMIT 1",
            (state_id, key, key, key),
        )
    ).fetchone()
    if row:
        return row["id"], None
    near = await (
        await conn.execute(
            "SELECT name FROM locations WHERE kind = 'district' AND parent_id = %s "
            "ORDER BY similarity(name, %s) DESC LIMIT 3",
            (state_id, district.upper()),
        )
    ).fetchall()
    hint = f" Closest: {', '.join(r['name'] for r in near)}." if near else ""
    return None, (
        f"{district!r} is not a district of {state} in the Local Government Directory. Not created — "
        f"a misspelling that becomes a district row is wrong for good.{hint}"
    )
