"""fetch_page, with no database: a query given LIMIT / OFFSET, its total read back, and a bad tail refused."""

from __future__ import annotations

import pytest

from app.repositories import contacts, documents, funders, meta, orgs, partner_lines, programs, rfps, scores
from app.repositories.paging import _ENDS_IN_ID, fetch_page

SQL = "SELECT id, COUNT(*) OVER () AS total FROM t WHERE k = %(k)s ORDER BY name, id"


async def test_fetch_page_adds_limit_and_offset_and_reads_the_total(recording_pool):
    pool = recording_pool([{"id": 4, "total": 12}, {"id": 5, "total": 12}])
    rows, total = await fetch_page(pool, SQL, {"k": "x"}, limit=2, offset=3)
    assert ([r["id"] for r in rows], total) == ([4, 5], 12)
    assert pool.sql.endswith("ORDER BY name, id\nLIMIT %(limit)s OFFSET %(offset)s")
    assert pool.params == {"k": "x", "limit": 2, "offset": 3}
    assert len(pool.calls) == 1


async def test_an_empty_first_page_has_a_total_of_zero_without_a_second_query(recording_pool):
    pool = recording_pool([])
    assert await fetch_page(pool, SQL, {"k": "x"}, limit=50, offset=0) == ([], 0)
    assert len(pool.calls) == 1


async def test_a_page_past_the_end_still_reports_the_lists_total(recording_pool):
    pool = recording_pool([], [{"id": 1, "total": 31}])
    assert await fetch_page(pool, SQL, {"k": "x"}, limit=25, offset=50) == ([], 31)
    probe_sql, probe_params = pool.calls[1]
    assert probe_sql.endswith("ORDER BY name, id\nLIMIT 1") and probe_params == {"k": "x"}


async def test_a_page_past_the_end_of_an_empty_list_is_zero(recording_pool):
    assert await fetch_page(recording_pool([], []), SQL, {}, limit=25, offset=50) == ([], 0)


@pytest.mark.parametrize("tail", [
    "ORDER BY name",                  # no unique tie-breaker
    "ORDER BY name, id;",             # a ';' would end the statement before the LIMIT
    "ORDER BY name, id LIMIT 10",     # its own LIMIT
    "ORDER BY name, id -- newest",    # a trailing comment
    "WHERE x IN (SELECT id FROM u ORDER BY id)",  # an ORDER BY only inside a subquery
])
async def test_sql_that_does_not_end_in_order_by_id_is_refused(recording_pool, tail):
    pool = recording_pool()
    with pytest.raises(ValueError, match="ORDER BY"):
        await fetch_page(pool, f"SELECT id, COUNT(*) OVER () AS total FROM t {tail}", {}, limit=5, offset=0)
    assert pool.calls == []


LISTS = [
    contacts.list_contacts, documents.list_documents, funders.list_funders, meta.list_tags, meta.list_locations,
    orgs.list_orgs, partner_lines.list_partner_lines, programs.list_programs, rfps.list_rfps, scores.list_scores,
]


@pytest.mark.parametrize("list_fn", LISTS, ids=lambda fn: fn.__name__)
async def test_every_paged_list_sorts_on_a_unique_id(recording_pool, list_fn):
    pool = recording_pool([{"id": 1, "total": 1}])
    await list_fn(pool, limit=5, offset=0)
    assert _ENDS_IN_ID.search(pool.sql.rsplit("\nLIMIT", 1)[0])
