"""make source-check: run the change check for one entity up to a stage, and print what each stage found."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.refresh import baseline, compare, diff, evidence, fetch_status

# The stages in the order they run; each new stage of the check is added here as it lands.
STAGES = ("baseline", "fetch", "hash", "diff", "evidence")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="make source-check", description=__doc__)
    parser.add_argument("--slug", required=True, help="the entity's slug, as in entity_research.slug")
    parser.add_argument("--until", choices=STAGES, default=STAGES[-1],
                        help="stop after this stage and print what it found (default: the last)")
    return parser.parse_args(argv)


async def main(slug: str, until: str) -> None:
    """Each stage prints what it found; the check stops after `until`, or when nothing is left to check."""
    pool = make_pool(get_settings().database_url, max_size=1)
    await pool.open()
    try:
        async with pool.connection() as conn:
            baselines, unrecorded = await baseline.load(conn, slug)
            findings = await evidence.load_findings(conn, slug)
    finally:
        await pool.close()
    print(baseline.describe(slug, baselines, unrecorded))
    if until == "baseline" or not baselines:
        return
    with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
        today = await fetch_status.fetch_all(baselines, Path(scratch))
    print(fetch_status.describe(slug, today))
    if until == "fetch":
        return
    checks = compare.compare(baselines, today)
    print(compare.describe(slug, checks))
    if until == "hash":
        return
    checks = await diff.run(checks)
    print(diff.describe(slug, checks))
    if until == "diff":
        return
    print(evidence.describe(slug, evidence.run(checks, findings)))


if __name__ == "__main__":
    args = parse()
    asyncio.run(main(args.slug, args.until))
