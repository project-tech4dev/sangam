"""Resolving a place name from a report to a row in `locations`.

Two things make this more than a lookup. Reports name places loosely — "Orissa",
"NCT of Delhi", "Kamrup Metropolitan" — and `funder_footprints.location_id` is
NOT NULL, so a footprint with an unresolvable place cannot be written at all.

The state list is closed and the district list is not. A state that is not one
of the thirty-six is a refusal, because a typo becoming a state row is a
permanent wrong answer; a district unknown to us is created under its stated
state, because there is no offline list of 780 districts to check it against
and refusing every one would mean never recording a footprint.
"""

from __future__ import annotations

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
    """Find this place or create it. Matching is case-insensitive because the
    seed writes states in title case and districts in upper case, and a second
    row for the same place is worse than an inconsistent one."""
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
    """The locations row for a place, creating it if need be.

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
    # Districts are stored upper case, following the seed, which takes them
    # from Darpan's own upper-case city_of_registration.
    return await _ensure(conn, "district", district.strip().upper(), state_id), None
