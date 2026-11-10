"""One page of a SQL list and how many it holds, shared by every paged repository."""

from __future__ import annotations

from typing import Any


async def fetch_page(pool: Any, sql: str, params: dict, *, limit: int, offset: int) -> tuple[list[dict], int]:
    """(rows, total) for `sql`, which selects `COUNT(*) OVER () AS total` and ends with its ORDER BY."""
    async with pool.connection() as conn:
        cur = await conn.execute(f"{sql}\nLIMIT %(limit)s OFFSET %(offset)s",
                                 {**params, "limit": limit, "offset": offset})
        rows = await cur.fetchall()
    return rows, (rows[0]["total"] if rows else 0)
