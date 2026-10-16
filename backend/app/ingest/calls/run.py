"""make calls-pull: one pull of funders' open calls; make calls-match: only match the open calls to orgs."""

from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.calls import pull
from app.integrations.tracing import configure_langfuse, flush_traces
from app.repositories import rfps


async def match_only() -> int:
    pool = make_pool(get_settings().database_url, max_size=1)
    await pool.open()
    try:
        print(pull.match_line(await rfps.flag_matches(pool)))
        return 0
    finally:
        await pool.close()


async def main(funders: list[str], *, yes: bool) -> int:
    if not funders and not yes:
        print("calls-pull: this reads every funder's site (one search and two model calls each); "
              "rerun with CONFIRM=1 to go ahead, or FUNDER=<slug> for one.")
        return 2
    settings = get_settings()
    configure_langfuse(settings)
    pool = make_pool(settings.database_url, max_size=pull.PARALLEL + 1)
    await pool.open()
    try:
        for line in await pull.run(pool, pull.Deps.from_settings(settings), funders or None):
            print(line)
        return 0
    finally:
        await pool.close()
        flush_traces()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--funder", action="append", default=[])
    p.add_argument("--yes", action="store_true", help="confirm a pull of every funder (make calls-pull CONFIRM=1)")
    p.add_argument("--match", action="store_true", help="read nothing; match the open calls to orgs")
    a = p.parse_args()
    raise SystemExit(asyncio.run(match_only() if a.match else main(a.funder, yes=a.yes)))
