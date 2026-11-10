"""registry_page_sql, the query GET /api/registry runs, against Postgres: every filter, the sort, the cut, the counts."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.repositories.registry import Filters, registry_page_sql
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration


async def _id(db, sql: str, params: tuple = ()) -> int:
    return (await (await db.execute(sql + " RETURNING id", params)).fetchone())["id"]


async def _state(db, name: str) -> int:
    row = await (await db.execute(
        "SELECT id FROM locations WHERE kind = 'state' AND name = %s AND parent_id IS NULL", (name,))).fetchone()
    return row["id"] if row else await _id(db, "INSERT INTO locations (kind, name) VALUES ('state', %s)", (name,))


@pytest.fixture
async def world(db):
    """Three CSOs and two funders, every name carrying `t`, so q=t lists exactly them on a seeded database too."""
    t = uuid4().hex[:8]
    assam, goa = await _state(db, "Assam"), await _state(db, f"Goa {t}")
    domain = await _id(db, "INSERT INTO tags (slug, label, kind, domain) VALUES (%s, %s, 'domain', %s)",
                       (f"d-{t}", f"Dom {t}", f"Dom {t}"))
    theme = await _id(db, "INSERT INTO tags (slug, label, kind, parent_id) VALUES (%s, 'Creches', 'theme', %s)",
                      (f"th-{t}", domain))
    women = await _id(db, "INSERT INTO tags (slug, label, kind) VALUES (%s, %s, 'population')", (f"p-{t}", f"Pop {t}"))
    sdg = await _id(db, "INSERT INTO tags (slug, label, kind, code) VALUES (%s, 'Probe goal', 'sdg', %s)",
                    (f"s-{t}", f"9{t[:3]}"))
    await db.execute("INSERT INTO tag_links (tag_id, linked_tag_id) VALUES (%s, %s)", (theme, sdg))

    alpha = await _id(db, "INSERT INTO orgs (slug, name, aliases) VALUES (%s, %s, %s)",
                      (f"a-{t}", f"Alpha {t}", [f"Akabil{t}"]))
    beta = await _id(db, "INSERT INTO orgs (slug, name) VALUES (%s, %s)", (f"b-{t}", f"beta {t}"))
    await _id(db, "INSERT INTO orgs (slug, name) VALUES (%s, %s)", (f"c-{t}", f"Ćhi {t}"))
    fund = await _id(db, "INSERT INTO funders (slug, name, funder_type, intake_mode) "
                         "VALUES (%s, %s, 'corporate_foundation', 'invitation_only')", (f"f-{t}", f"Fund {t}"))
    grants = await _id(db, "INSERT INTO funders (slug, name, funder_type) VALUES (%s, %s, 'foundation')",
                       (f"g-{t}", f"Grants {t}"))

    await db.execute("INSERT INTO org_tags (org_id, tag_id) VALUES (%s, %s), (%s, %s)", (alpha, theme, alpha, women))
    await db.execute("INSERT INTO org_locations (org_id, location_id) VALUES (%s, %s), (%s, %s)",
                     (alpha, assam, beta, goa))
    await db.execute("INSERT INTO funder_locations (funder_id, location_id) VALUES (%s, %s)", (fund, assam))
    await db.execute("INSERT INTO org_identifiers (org_id, id_type) VALUES (%s, 'csr1'), (%s, 'fcra'), "
                     "(%s, '12a'), (%s, '80g')", (alpha, alpha, beta, beta))
    await db.execute("INSERT INTO programs (org_id, name, kind) VALUES (%s, %s, 'programme')", (beta, f"Water {t}"))
    await db.execute("INSERT INTO rfps (funder_id, title) VALUES (%s, 'Open call')", (grants,))
    return {"t": t, "pool": _PoolOf(db), "sdg": f"9{t[:3]}"}


async def _names(w, limit: int = 25, offset: int = 0, **filters) -> list[str]:
    page = await registry_page_sql(w["pool"], w["pool"], Filters(q=w["t"], **filters), limit=limit, offset=offset)
    return [r["name"].removesuffix(f" {w['t']}") for r in page["items"]]


async def test_csos_come_first_then_funders_each_a_to_z_ignoring_case(world):
    assert await _names(world) == ["Alpha", "beta", "Ćhi", "Fund", "Grants"]


async def test_kind_theme_population_and_sdg(world):
    t = world["t"]
    assert await _names(world, kind="org") == ["Alpha", "beta", "Ćhi"]
    assert await _names(world, kind="funder") == ["Fund", "Grants"]
    assert await _names(world, theme=f"Dom {t}") == ["Alpha"]
    assert await _names(world, population=f"Pop {t}") == ["Alpha"]
    assert await _names(world, sdg=world["sdg"]) == ["Alpha"]
    assert await _names(world, theme="no-such-theme") == []


async def test_where_reads_the_north_east_outside_it_or_one_state(world):
    assert await _names(world, where="ne") == ["Alpha", "Fund"]
    assert await _names(world, where="out") == ["beta"]
    assert await _names(world, where=f"Goa {world['t']}") == ["beta"]


async def test_registrations_apply_to_csos_only(world):
    assert await _names(world, kind="org", reg="csr1") == ["Alpha"]
    assert await _names(world, kind="org", reg="fcra") == ["Alpha"]
    assert await _names(world, kind="org", reg="12a80g") == ["beta"]
    assert len(await _names(world, reg="fcra")) == 5


async def test_funder_type_and_approach_apply_to_funders_only(world):
    assert await _names(world, kind="funder", ftype="corporate_foundation") == ["Fund"]
    assert await _names(world, kind="funder", approach="invites") == ["Fund"]
    assert await _names(world, kind="funder", approach="open") == ["Grants"]
    assert len(await _names(world, ftype="corporate_foundation")) == 5


async def test_search_reads_aliases_programmes_and_states_inside_a_word_ignoring_case(world):
    t, pool = world["t"], world["pool"]

    async def found(q: str) -> list[str]:
        page = await registry_page_sql(pool, pool, Filters(q=q), limit=25, offset=0)
        return sorted(r["slug"] for r in page["items"] if r["slug"].endswith(t))

    assert await found(f"kabil{t}") == [f"a-{t}"]
    assert await found(f"  WATER {t} ") == [f"b-{t}"]
    assert await found(f"goa {t}") == [f"b-{t}"]


async def test_filters_combine(world):
    assert await _names(world, kind="org", theme=f"Dom {world['t']}", where="ne") == ["Alpha"]
    assert await _names(world, kind="org", where="out", reg="csr1") == []


async def test_limit_and_offset_cut_a_page_and_the_total_counts_every_match(world):
    pool = world["pool"]
    page = await registry_page_sql(pool, pool, Filters(q=world["t"]), limit=2, offset=2)
    assert [r["slug"][:2] for r in page["items"]] == ["c-", "f-"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 2)
    past = await registry_page_sql(pool, pool, Filters(q=world["t"]), limit=25, offset=500)
    assert past["items"] == [] and past["total"] == 5


async def test_counts_and_options_cover_the_whole_registry_whatever_the_filters(world):
    t, pool = world["t"], world["pool"]
    page = await registry_page_sql(pool, pool, Filters(kind="funder", q=t), limit=25, offset=0)
    assert page["counts"]["all"] == page["counts"]["org"] + page["counts"]["funder"] >= 5
    options = {name: {o.value: o.count for o in opts} for name, opts in page["facets"].items()}
    assert set(options) == {"theme", "population", "sdg", "where", "ftype", "approach"}
    assert options["theme"][f"Dom {t}"] == 1 and options["population"][f"Pop {t}"] == 1
    assert options["sdg"][world["sdg"]] == 1 and options["where"][f"Goa {t}"] == 1
    assert {"open", "invites"} <= set(options["approach"])


async def test_a_page_row_carries_what_its_card_shows(world):
    t, pool = world["t"], world["pool"]
    page = await registry_page_sql(pool, pool, Filters(kind="org", q=t), limit=1, offset=0)
    (alpha,) = page["items"]
    assert alpha["themes"] == [{"label": "Creches", "domain": f"Dom {t}"}]
    assert alpha["populations"] == [f"Pop {t}"] and alpha["sdgs"] == [world["sdg"]]
    assert alpha["states"] == ["Assam"] and alpha["csr1"] and alpha["fcra"] and not alpha["has_12a_80g"]


class _Recording(_PoolOf):
    """The test's connection as the owner pool, noting each query's text and parameters."""

    def __init__(self, conn):
        super().__init__(conn)
        self.ran: list[tuple[str, dict]] = []
        recording = self

        class _Conn:
            async def execute(self, sql, params=None):
                recording.ran.append((sql, params or {}))
                return await conn.execute(sql, params)

        self._conn = _Conn()


async def test_registrations_are_read_for_the_page_orgs_only_and_not_before_the_query(world, db):
    owner = _Recording(db)
    page = await registry_page_sql(world["pool"], owner, Filters(q=world["t"]), limit=2, offset=0)
    assert [r["name"].split()[0] for r in page["items"]] == ["Alpha", "beta"]
    assert len(owner.ran) == 1  # no read of the whole table first
    sql, params = owner.ran[0]
    assert "org_id = ANY(%(ids)s)" in sql and params["ids"] == [r["id"] for r in page["items"]]


async def test_a_page_of_funders_reads_no_registrations(world, db):
    owner = _Recording(db)
    await registry_page_sql(world["pool"], owner, Filters(kind="funder", q=world["t"]), limit=25, offset=0)
    assert owner.ran == []


async def test_a_registrations_filter_asks_only_for_the_orgs_it_keeps(world, db):
    owner = _Recording(db)
    page = await registry_page_sql(world["pool"], owner, Filters(kind="org", reg="12a80g", q=world["t"]),
                                   limit=25, offset=0)
    assert [r["name"].split()[0] for r in page["items"]] == ["beta"] and page["items"][0]["has_12a_80g"]
    (filter_sql, filter_params), (badge_sql, _) = owner.ran
    assert "HAVING" in filter_sql and filter_params == {"needs": ["12a", "80g"]}
    assert "org_id = ANY(%(ids)s)" in badge_sql
