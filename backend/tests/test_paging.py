"""fetch_page, with no database: a query given LIMIT / OFFSET, its total read back, and a bad tail refused."""

from __future__ import annotations

import pytest

from app.repositories import contacts, documents, funders, meta, orgs, partner_lines, programs, rfps, scores
from app.repositories.paging import fetch_page

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
    pool = recording_pool([], [{"total": 31}])
    assert await fetch_page(pool, SQL, {"k": "x"}, limit=25, offset=50) == ([], 31)
    count_sql, count_params = pool.calls[1]
    assert count_sql == f"SELECT count(*) AS total FROM (\n{SQL}\n) listed" and count_params == {"k": "x"}


async def test_a_page_past_the_end_of_an_empty_list_is_zero(recording_pool):
    assert await fetch_page(recording_pool([], [{"total": 0}]), SQL, {}, limit=25, offset=50) == ([], 0)


@pytest.mark.parametrize("tail", ["ORDER BY name, id DESC", "ORDER BY created DESC, t.id DESC NULLS LAST"])
async def test_an_id_with_a_direction_still_counts_as_the_last_key(recording_pool, tail):
    pool = recording_pool([])
    await fetch_page(pool, f"SELECT id, COUNT(*) OVER () AS total FROM t {tail}", {}, limit=5, offset=0)
    assert len(pool.calls) == 1


@pytest.mark.parametrize("tail", [
    "ORDER BY name",                  # no unique tie-breaker
    "ORDER BY name, id;",             # a ';' would end the statement before the LIMIT
    "ORDER BY name, id LIMIT 10",     # its own LIMIT
    "ORDER BY name, id -- newest",    # a trailing comment
    "ORDER BY name -- ties by id",    # a comment that happens to end in id
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
    await list_fn(pool, limit=5, offset=0)  # fetch_page raises before querying when the sort does not end in id
    assert len(pool.calls) == 1
