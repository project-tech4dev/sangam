"""registry_page_sql, the query /api/registry/page runs, against Postgres: it must agree with registry_page."""

from __future__ import annotations

import pytest

from app.repositories.registry import Filters, registry_page, registry_page_sql, registry_rows
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration


async def seed(db) -> None:
    """A few rows of each kind, so a fresh CI database still has something to filter and sort."""
    for slug, name in [("reg-probe-a", "Registry Probe Alpha"), ("reg-probe-b", "registry probe beta"),
                       ("reg-probe-c", "Registry Probe Ćhi")]:
        await db.execute("INSERT INTO orgs (slug, name) VALUES (%s, %s)", (slug, name))
    for slug, name, ftype, mode in [("reg-probe-f", "Registry Probe Fund", "corporate_foundation", "invitation_only"),
                                    ("reg-probe-g", "Registry Probe Grants", "foundation", None)]:
        await db.execute("INSERT INTO funders (slug, name, funder_type, intake_mode) VALUES (%s, %s, %s, %s)",
                         (slug, name, ftype, mode))


def cases(rows: list[dict]) -> list[Filters]:
    """Every branch of _where, with a real value for each facet when the data has one."""
    def first(key: str, default: str) -> str:
        return next((v for r in rows for v in (r.get(key) or [])), default)

    theme = next((t["domain"] for r in rows for t in r["themes"] if t["domain"]), "Health")
    state = first("states", "Assam")
    out = [
        Filters(), Filters(kind="org"), Filters(kind="funder"),
        Filters(theme=theme), Filters(population=first("populations", "Women")), Filters(sdg=first("sdgs", "4")),
        Filters(where="ne"), Filters(where="out"), Filters(where=state),
        Filters(kind="funder", ftype="corporate_foundation"), Filters(kind="funder", approach="open"),
        Filters(kind="funder", approach="invites"),
        Filters(q="probe"), Filters(q="  PROBE beta "), Filters(q="no-such-entity-anywhere"),
        Filters(kind="org", theme=theme, where="ne", q="a"),
    ]
    out += [Filters(kind="org", reg=reg) for reg in ("csr1", "12a80g", "fcra")]
    return out


async def test_the_sql_page_agrees_with_the_python_page_on_every_filter(db):
    await seed(db)
    pool = _PoolOf(db)
    rows = await registry_rows(pool, pool)
    for f in cases(rows):
        for offset in (0, 2):
            sql = await registry_page_sql(pool, pool, f, limit=2, offset=offset)
            assert sql == registry_page([dict(r) for r in rows], f, limit=2, offset=offset), (f, offset)


async def test_a_page_past_the_end_is_empty_with_the_total(db):
    await seed(db)
    pool = _PoolOf(db)
    page = await registry_page_sql(pool, pool, Filters(q="registry probe"), limit=25, offset=500)
    assert page["items"] == [] and page["total"] == 5
