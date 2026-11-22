"""make source-check: run the change check for one entity up to a stage, and print what each stage found."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.refresh import baseline, compare, decision, service
from app.integrations.tracing import configure_langfuse, flush_traces, traced_job

# The stages in the order they run; each new stage of the check is added here as it lands.
STAGES = ("baseline", "fetch", "hash", "diff", "evidence", "judge", "discover", "gaps")


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
    settings = get_settings()
    configure_langfuse(settings)  # the API's lifespan does this; a CLI check has no lifespan
    pool = make_pool(settings.database_url, max_size=1)
    await pool.open()
    try:
        if write:
            try:
                await service.run(pool, slug, service.FULL, refresh, None, say=print)  # traced inside, like the screen
            except service.NoBaseline:
                pass  # the baseline's own line already said there is nothing to check
            except service.Busy:
                print(f"{slug}: a check is already running; try again when it finishes")
            return
        session = f"source-check-{uuid.uuid4()}"
        await traced_job(settings, "sangam_source_check", lambda: _look(pool, slug, until),
                         inputs={"slug": slug, "until": until}, session_id=session, tags=("source-check", "cli"))
    finally:
        await pool.close()
        flush_traces()


async def _look(pool: Any, slug: str, until: str) -> dict[str, Any]:
    """A check that saves nothing, printed stage by stage; what it returns is the trace's output."""
    async with pool.connection() as conn:
        given = await service.load_inputs(conn, slug)
    print(baseline.describe(slug, given.baselines, given.unrecorded))
    if until == "baseline" or not given.baselines:
        return {"stopped_after": "baseline", "sources": len(given.baselines)}
    with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
        ended = await service.stages(slug, service.FULL, Path(scratch), given, until=until, say=print)
    if ended is None:
        return {"stopped_after": until}
    checks, found, verdict = ended
    return {"decision": verdict, "sources": compare.counts(checks), "new_sources": len(found.new),
            "gap_sources": decision.gap_sources(found)}


if __name__ == "__main__":
    args = parse()
    asyncio.run(main(args.slug, args.until, args.write, args.refresh))
