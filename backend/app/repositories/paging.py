"""One page of a SQL list and how many it holds, shared by every paged repository."""

from __future__ import annotations

import re
from typing import Any

# The outermost ORDER BY must be the last clause and end in the row's id, or tied rows can move between pages.
# No '(', ';' or '-' after it, so a subquery's ORDER BY, a second statement or a comment cannot pass.
_ENDS_IN_ID = re.compile(
    r"\bORDER\s+BY\s[^();\-]*\b(?:\w+\.)?id(?:\s+(?:ASC|DESC))?(?:\s+NULLS\s+(?:FIRST|LAST))?\s*$", re.IGNORECASE)


async def fetch_page(pool: Any, sql: str, params: dict, *, limit: int, offset: int) -> tuple[list[dict], int]:
    """(rows, total) for `sql`, which selects `COUNT(*) OVER () AS total` and ends with an ORDER BY ending in id."""
    sql = sql.rstrip()
    if not _ENDS_IN_ID.search(sql):
        raise ValueError("fetch_page needs SQL that ends in ORDER BY … id, with no LIMIT, ';' or comment after it")
    async with pool.connection() as conn:
        rows = await (await conn.execute(f"{sql}\nLIMIT %(limit)s OFFSET %(offset)s",
                                         {**params, "limit": limit, "offset": offset})).fetchall()
        if rows or offset == 0:
            return rows, (rows[0]["total"] if rows else 0)
        # Past the end the page is empty but the list may not be. A plain count lets Postgres skip the columns.
        counted = await (await conn.execute(f"SELECT count(*) AS total FROM (\n{sql}\n) listed", params)).fetchall()
    return rows, counted[0]["total"]
