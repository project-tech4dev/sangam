"""make pool-load: upsert the funder-pool export into funder_pool. Safe to run twice."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.db.checkpointer import make_pool

COLUMNS = ("pool_funder_id", "category", "name", "cin", "rank_in_category", "score_total",
           "csr_spend_3y_avg_cr", "in_sangam_at_load", "ingest_status", "export_version", "signals")

# A newer export refreshes only what ranks and describes a candidate; ingest state, links and CIN stay the worker's.
UPSERT = f"""
INSERT INTO funder_pool ({", ".join(COLUMNS)})
VALUES ({", ".join("%s::jsonb" if c == "signals" else "%s" for c in COLUMNS)})
ON CONFLICT (pool_funder_id) DO UPDATE SET
  name = EXCLUDED.name, rank_in_category = EXCLUDED.rank_in_category, score_total = EXCLUDED.score_total,
  csr_spend_3y_avg_cr = EXCLUDED.csr_spend_3y_avg_cr, signals = EXCLUDED.signals,
  export_version = EXCLUDED.export_version, updated_at = now()
RETURNING (xmax = 0) AS inserted
"""

COUNTS = "SELECT category, ingest_status, count(*) AS n FROM funder_pool GROUP BY 1, 2 ORDER BY 1, 2"


def _blank(value: str | None) -> str | None:
    return None if value is None or value.strip() == "" else value.strip()


def row_values(row: dict[str, str]) -> tuple[Any, ...]:
    """One CSV row as UPSERT parameters: blanks are NULL, signals is JSON text and an empty one is {}."""
    if missing := [c for c in COLUMNS if c not in row]:
        raise ValueError(f"the file has no column {', '.join(missing)}")
    values = {c: _blank(row[c]) for c in COLUMNS}
    values["signals"] = json.dumps(json.loads(values["signals"]) if values["signals"] else {})
    values["ingest_status"] = values["ingest_status"] or "pending"
    if values["rank_in_category"] is not None:
        values["rank_in_category"] = int(values["rank_in_category"])
    return tuple(values[c] for c in COLUMNS)


def read_rows(path: Path) -> list[tuple[Any, ...]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [row_values(r) for r in csv.DictReader(f)]


async def load(pool: Any, rows: list[tuple[Any, ...]]) -> tuple[int, int, list[dict[str, Any]]]:
    """(inserted, updated, counts by category and status) after upserting every row in one transaction."""
    async with pool.connection() as conn, conn.transaction():
        async with conn.cursor() as cur:
            await cur.executemany(UPSERT, rows, returning=True)
            inserted = 0
            while True:
                if (r := await cur.fetchone()) and r["inserted"]:
                    inserted += 1
                if not cur.nextset():
                    break
        counts = await (await conn.execute(COUNTS)).fetchall()
    return inserted, len(rows) - inserted, counts


async def main(path: Path) -> int:
    rows = read_rows(path)
    pool = make_pool(get_settings().database_url, max_size=2)
    await pool.open()
    try:
        inserted, updated, counts = await load(pool, rows)
    finally:
        await pool.close()
    print(f"read {len(rows)} rows: {inserted} inserted, {updated} updated")
    for c in counts:
        print(f"  {c['category']:<24} {c['ingest_status']:<13} {c['n']:>7}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("file", type=Path, help="funder_pool_load.csv from the funder-pool export")
    raise SystemExit(asyncio.run(main(p.parse_args().file)))
