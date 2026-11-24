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
    delta,
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
    parser.add_argument("--refresh", action="store_true",
                        help="with --write: when the decision is refresh, save a delta as today's research row")
    args = parser.parse_args(argv)
    if args.write and args.until != STAGES[-1]:
        parser.error("--write saves what every stage found, so it cannot stop early with --until")
    if args.refresh and not args.write:
        parser.error("--refresh needs --write: the delta cites the versions --write archives")
    return args


async def main(slug: str, until: str, write: bool = False, refresh: bool = False) -> None:
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
        if not write or ended is None:
            return
        checks, found, verdict = ended
        keys = await save.archive_all(checks, found)
        run_id = uuid.uuid4()
        async with _connection() as conn:
            saved = await save.write(conn, run_id, slug, checks, found, keys)
        print(save.describe(slug, run_id, saved))
        if refresh and verdict == decision.REFRESH:
            await _refresh(slug, checks, found, context, saved)
        elif refresh:
            print(f"{slug}: no refresh: the decision is {verdict}")


async def _refresh(slug: str, checks: list[compare.Check], found: discover.Discovery, context: judge.Context,
                   saved: save.Saved) -> None:
    """The delta is asked for with no connection held; the brief waits for the person's save in Review & save."""
    settings = get_settings()
    async with _connection() as conn:
        entity, rows = await delta.load(conn, slug)
        today = entity is not None and await delta.researched_today(conn, slug)
    if entity is None:
        print(f"{slug}: no refresh: no research row to carry forward")
        return
    if today:
        print(f"{slug}: no refresh: it was already researched today")
        return
    srcs = delta.sources(checks, found, delta.facts_by_url(rows))
    # Sonnet refuses a forced tool call for structured output, so the delta asks for a JSON schema.
    model = resolve_model(settings.research_model).with_structured_output(delta.Delta, method="json_schema")
    grader = resolve_model(settings.utility_model).with_structured_output(delta.Grade)
    proposed, problems = await delta.propose(model, grader, delta.ask(entity["canonical_name"] or entity["entity_name"],
                                                                       srcs, context))
    applied = delta.apply(proposed, srcs)
    read = [s.url for s in srcs if s.status != "dead"]
    async with _connection() as conn, conn.transaction():
        row_id = await delta.save_row(conn, entity, applied, proposed, context,
                                      [saved.snapshot_ids[u] for u in read if u in saved.snapshot_ids], read)
    print(delta.describe(slug, applied, row_id, problems))


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
                  subject: discover.Subject | None) -> tuple[list[compare.Check], discover.Discovery, str] | None:
    """The stages after the baseline; the checks and the discovery when every stage ran, else None."""
    settings = get_settings()
    today = await fetch_status.fetch_all(baselines, scratch)
    print(fetch_status.describe(slug, today))
    if until == "fetch":
        return None
    checks = compare.compare(baselines, today)
    print(compare.describe(slug, checks))
    if until == "hash":
        return None
    checks = await diff.run(checks)
    print(diff.describe(slug, checks))
    redesign = decision.redesigned(checks)
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
        # Rows saved before snapshots have no baseline, but their cited URLs were read all the same.
        known_urls = {b.url for b in baselines} | set(findings)
        known_hashes = {b.text_hash for b in baselines} | {t.fingerprint for t in today if t.fingerprint}
        async with httpx.AsyncClient() as client:
            found = await discover.run(subject, known_urls, known_hashes, context,
                                       model.with_structured_output(discover.Picks), settings.tavily_api_key,
                                       client, scratch)
        print(discover.describe(slug, found))
    verdict = decision.decide(checks, found, redesign)
    print(decision.describe(slug, checks, found, verdict))
    return checks, found, verdict


if __name__ == "__main__":
    args = parse()
    asyncio.run(main(args.slug, args.until, args.write, args.refresh))
