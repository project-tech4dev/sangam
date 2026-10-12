"""make news-pull: one news pull from the command line, through the same code as Import's routes."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.news import pipeline, store
from app.ingest.news.bars import Bars
from app.ingest.news.feeds import feeds_for
from app.integrations.tracing import configure_langfuse, flush_traces


async def _ids(pool, table: str, slugs: list[str]) -> list[int]:
    async with pool.connection() as conn:
        rows = await (await conn.execute(f"SELECT id FROM {table} WHERE slug = ANY(%s)", (slugs,))).fetchall()
    return [r["id"] for r in rows]


def refusal(*, chosen: bool, org_ids: list[int] | None, funder_ids: list[int] | None, yes: bool) -> str | None:
    """Why this pull must not run: a misspelt slug must never widen into the whole Registry, billed."""
    if chosen and not (org_ids or funder_ids):
        return "news-pull: that ORG/FUNDER matches no Registry record; nothing pulled."
    if not chosen and not yes:
        return "news-pull: this pulls every Registry record and the topic feeds; rerun with CONFIRM=1 to go ahead."
    return None


async def main(orgs: list[str], funders: list[str], *, visibility_only: bool = False,
               yes: bool = False) -> int:
    settings = get_settings()
    configure_langfuse(settings)  # the API's lifespan does this; a CLI pull has no lifespan
    pool = make_pool(settings.database_url, max_size=4)  # as app/matching/run.py does
    await pool.open()
    try:
        if visibility_only:
            async with pool.connection() as conn:
                print(await store.recompute_visibility(conn, Bars.from_settings(settings)))
            return 0
        chosen = bool(orgs or funders)
        org_ids = await _ids(pool, "orgs", orgs) if chosen else None
        funder_ids = await _ids(pool, "funders", funders) if chosen else None
        keys = feeds_for(everyone=not chosen)
        p = await pipeline.plan_for(pool, org_ids=org_ids, funder_ids=funder_ids, feeds=keys)
        print(f"plan: {p.line}")
        if why := refusal(chosen=chosen, org_ids=org_ids, funder_ids=funder_ids, yes=yes):
            print(why)
            return 2
        run_id = await pipeline.create_run(pool, org_ids=org_ids, funder_ids=funder_ids, feeds=keys, started_by=None)
        print(json.dumps(await pipeline.execute_run(pool, run_id, pipeline.Deps.from_settings(settings)),
                         default=str, indent=1))
        return 0
    finally:
        await pool.close()
        flush_traces()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--org", action="append", default=[])
    p.add_argument("--funder", action="append", default=[])
    p.add_argument("--visibility", action="store_true", help="only rewrite visibility from stored scores")
    p.add_argument("--yes", action="store_true", help="confirm a pull of everyone (make news-pull CONFIRM=1)")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.org, a.funder, visibility_only=a.visibility, yes=a.yes)))
