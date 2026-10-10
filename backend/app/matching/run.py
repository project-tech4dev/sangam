"""make match: save a run for every org, or one, written as the owner with run_by NULL."""

from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.matching.service import run_and_save


async def main(org: str | None) -> None:
    pool = make_pool(get_settings().database_url, max_size=2)
    await pool.open()
    try:
        async with pool.connection() as conn:
            where = " WHERE slug = %(v)s OR id::text = %(v)s" if org else ""
            sql = f"SELECT id, slug FROM orgs{where} ORDER BY id"
            orgs = await (await conn.execute(sql, {"v": org})).fetchall()
        if org and not orgs:
            raise SystemExit(f"no org {org}")
        for o in orgs:
            run = await run_and_save(pool, pool, o["id"], None)
            print(f"{o['slug']}: {run['funders_checked']} funders, {run['tiers']} run {run['run_id']}")
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", help="one org's slug or id; every org when omitted")
    asyncio.run(main(parser.parse_args().org))
