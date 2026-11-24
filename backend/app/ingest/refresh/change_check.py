"""make source-check: run the change check for one entity up to a stage, and print what each stage found."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.refresh import baseline, service

# The stages in the order they run; each new stage of the check is added here as it lands.
STAGES = ("baseline", "fetch", "hash", "diff", "evidence", "judge", "discover")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="make source-check", description=__doc__)
    parser.add_argument("--slug", required=True, help="the entity's slug, as in entity_research.slug")
    parser.add_argument("--until", choices=STAGES, default=STAGES[-1],
                        help="stop after this stage and print what it found (default: the last)")
    parser.add_argument("--write", action="store_true",
                        help="archive what differed and save one source_checks row per source (every stage runs)")
    parser.add_argument("--refresh", action="store_true",
                        help="with --write: when the decision is refresh, save a delta as today's research row")
    args = parser.parse_args(argv)
    if args.write and args.until != STAGES[-1]:
        parser.error("--write saves what every stage found, so it cannot stop early with --until")
    if args.refresh and not args.write:
        parser.error("--refresh needs --write: the delta cites the versions --write archives")
    return args


async def main(slug: str, until: str, write: bool = False, refresh: bool = False) -> None:
    """The screen's pipeline, printed stage by stage. WRITE=1 is a recorded run like the screen's: it shows in the
    screen's history and waits for a check already running."""
    pool = make_pool(get_settings().database_url, max_size=1)
    await pool.open()
    try:
        if write:
            try:
                await service.run(pool, slug, service.FULL, refresh, None, say=print)
            except service.NoBaseline:
                pass  # the baseline's own line already said there is nothing to check
            except service.Busy:
                print(f"{slug}: a check is already running; try again when it finishes")
            return
        async with pool.connection() as conn:
            given = await service.load_inputs(conn, slug)
        print(baseline.describe(slug, given.baselines, given.unrecorded))
        if until == "baseline" or not given.baselines:
            return
        with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
            await service.stages(slug, service.FULL, Path(scratch), given, until=until, say=print)
    finally:
        await pool.close()


if __name__ == "__main__":
    args = parse()
    asyncio.run(main(args.slug, args.until, args.write, args.refresh))
