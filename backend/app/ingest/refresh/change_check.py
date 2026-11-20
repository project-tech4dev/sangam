"""make source-check: run the change check for one entity up to a stage, and print what each stage found."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from app.agentkit.models import resolve_model
from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest.refresh import (
    baseline,
    compare,
    decision,
    diff,
    discover,
    evidence,
    fetch_status,
    judge,
    save,
)

# The stages in the order they run; each new stage of the check is added here as it lands.
STAGES = ("baseline", "fetch", "hash", "diff", "evidence", "judge", "discover")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="make source-check", description=__doc__)
    parser.add_argument("--slug", required=True, help="the entity's slug, as in entity_research.slug")
    parser.add_argument("--until", choices=STAGES, default=STAGES[-1],
                        help="stop after this stage and print what it found (default: the last)")
    parser.add_argument("--write", action="store_true",
                        help="archive what differed and save one source_checks row per source (every stage runs)")
    args = parser.parse_args(argv)
    if args.write and args.until != STAGES[-1]:
        parser.error("--write saves what every stage found, so it cannot stop early with --until")
    return args


async def main(slug: str, until: str, write: bool = False) -> None:
    """Each stage prints what it found; the check stops after `until`, or when nothing is left to check.
    The database is held only to read at the start and, with write, to save at the end, never while fetching."""
    async with _connection() as conn:
        baselines, unrecorded = await baseline.load(conn, slug)
        findings = await evidence.load_findings(conn, slug)
        context = await judge.load_context(conn, slug)
        subject = await discover.load_subject(conn, slug)
    print(baseline.describe(slug, baselines, unrecorded))
    if until == "baseline" or not baselines:
        return
    # One folder for the run: a document that differed is archived from it at the end.
    with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
        ended = await _stages(slug, until, Path(scratch), baselines, findings, context, subject)
        if write and ended is not None:
            checks, found = ended
            keys = await save.archive_all(checks)
            run_id = uuid.uuid4()
            async with _connection() as conn:
                print(save.describe(slug, run_id, await save.write(conn, run_id, slug, checks, found, keys)))


@asynccontextmanager
async def _connection() -> AsyncIterator[Any]:
    pool = make_pool(get_settings().database_url, max_size=1)
    await pool.open()
    try:
        async with pool.connection() as conn:
            yield conn
    finally:
        await pool.close()


async def _stages(slug: str, until: str, scratch: Path, baselines: list[baseline.Baseline],
                  findings: dict[str, list[str]], context: judge.Context,
                  subject: discover.Subject | None) -> tuple[list[compare.Check], discover.Discovery] | None:
    """The stages after the baseline; the checks and the discovery when every stage ran, else None."""
    settings = get_settings()
    # One source at a time: a check is not in a hurry, and a funder's site should not see a burst.
    today = [await fetch_status.fetch_today(b, scratch) for b in baselines]
    print(fetch_status.describe(slug, today))
    if until == "fetch":
        return None
    checks = compare.compare(baselines, today)
    print(compare.describe(slug, checks))
    redesign = decision.redesigned(checks)
    if until == "hash":
        return None
    checks = await diff.run(checks)
    print(diff.describe(slug, checks))
    if until == "diff":
        return None
    checks = evidence.run(checks, findings)
    print(evidence.describe(slug, checks))
    if until == "evidence":
        return None
    if redesign:
        # A full pull rereads everything, so neither the judge nor the search is worth paying for.
        checks = decision.settle(checks)
        found = discover.Discovery(skipped=decision.REDESIGN_REASON)
        print(f"{slug}: judge and discovery skipped: {decision.REDESIGN_REASON}")
        if until == "judge":
            return None
    else:
        model = resolve_model(settings.source_check_judge_model)
        checks = await judge.run(checks, findings, context, model.with_structured_output(judge.Judgement))
        print(judge.describe(slug, checks))
        if until == "judge":
            return None
        known_urls = {b.url for b in baselines}
        known_hashes = {b.text_hash for b in baselines} | {t.fingerprint for t in today if t.fingerprint}
        async with httpx.AsyncClient() as client:
            found = await discover.run(subject, known_urls, known_hashes, context,
                                       model.with_structured_output(discover.Picks), settings.tavily_api_key,
                                       client, scratch)
        print(discover.describe(slug, found))
    print(decision.describe(slug, checks, found, decision.decide(checks, found, redesign)))
    return checks, found


if __name__ == "__main__":
    args = parse()
    asyncio.run(main(args.slug, args.until, args.write))
