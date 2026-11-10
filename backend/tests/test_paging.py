"""fetch_page, with no database: a query given LIMIT / OFFSET, and its total read back."""

from __future__ import annotations

from contextlib import asynccontextmanager

from app.repositories.paging import fetch_page


class _Pool:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def connection(self):
        pool = self

        class _Conn:
            async def execute(self, sql, params):
                pool.sql, pool.params = sql, params

                class _Cur:
                    async def fetchall(self):
                        return pool.rows
                return _Cur()

        @asynccontextmanager
        async def held():
            yield _Conn()
        return held()


async def test_fetch_page_adds_limit_and_offset_and_reads_the_total():
    pool = _Pool([{"id": 4, "total": 12}, {"id": 5, "total": 12}])
    rows, total = await fetch_page(pool, "SELECT id, COUNT(*) OVER () AS total FROM t WHERE k = %(k)s ORDER BY id",
                                   {"k": "x"}, limit=2, offset=3)
    assert [r["id"] for r in rows] == [4, 5]
    assert total == 12
    assert pool.sql.endswith("ORDER BY id\nLIMIT %(limit)s OFFSET %(offset)s")
    assert pool.params == {"k": "x", "limit": 2, "offset": 3}


async def test_fetch_page_with_no_rows_has_a_total_of_zero():
    rows, total = await fetch_page(_Pool([]), "SELECT 1 AS total ORDER BY 1", {}, limit=50, offset=0)
    assert (rows, total) == ([], 0)
