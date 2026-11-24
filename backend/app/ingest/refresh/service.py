"""The change check, for the Scout screen and make source-check alike: one pipeline, every written run recorded."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from app.agentkit.models import resolve_model
from app.core.config import get_settings
from app.ingest.reading.access import canonical_url
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
from app.integrations.tracing import GENERATION_NAME, configure_langfuse, flush_traces, traced_job

logger = logging.getLogger(__name__)

FREE, FULL = "free", "full"
NEEDS_JUDGE = "needs the judge"  # a free run that found a page differing with every fact still on it
STALE_MINUTES = 30  # a run unfinished after this long died with its request; another may start

BUSY_SQL = f"""
    SELECT 1 FROM source_check_runs
     WHERE slug = %s AND finished_at IS NULL AND started_at > now() - interval '{STALE_MINUTES} minutes'
"""
# pg_advisory_xact_lock's two-key form: its own first key, so a slug's lock never meets Funder Match's (4104).
CHECK_LOCK = 4105
LOCK_SQL = "SELECT pg_advisory_xact_lock(%s, hashtext(%s))"
START_SQL = "INSERT INTO source_check_runs (run_id, slug, depth, requested_by) VALUES (%s, %s, %s, %s)"
FINISH_SQL = """
    UPDATE source_check_runs SET decision = %s, finished_at = now(), refresh_row_id = %s, refresh_summary = %s
     WHERE run_id = %s
"""
FAIL_SQL = "UPDATE source_check_runs SET error = %s, finished_at = now() WHERE run_id = %s"


class NoBaseline(Exception):
    """Nothing to compare with: no research row of the slug records which versions it read."""


class Busy(Exception):
    """A check of the same slug is still running."""


Say = Callable[[str], None]  # where each stage reports what it found: print for the CLI, nowhere for the screen


def _quiet(_line: str) -> None:
    return None


@dataclass(frozen=True)
class Inputs:
    """What every stage reads from the database, read once before anything is fetched."""

    baselines: list[baseline.Baseline]
    unrecorded: int
    findings: dict[str, list[str]]
    context: judge.Context
    subject: discover.Subject | None


async def load_inputs(conn: Any, slug: str) -> Inputs:
    baselines, unrecorded = await baseline.load(conn, slug)
    return Inputs(baselines, unrecorded, await evidence.load_findings(conn, slug),
                  await judge.load_context(conn, slug), await discover.load_subject(conn, slug))


@dataclass(frozen=True)
class Source:
    url: str
    kind: str | None
    snapshot_id: int
    read_on: str
    archived: bool
    facts: int


async def baseline_view(conn: Any, slug: str) -> tuple[list[Source], int]:
    """What a check would compare: each source, when it was read, and how many facts cite it."""
    baselines, unrecorded = await baseline.load(conn, slug)
    findings = await evidence.load_findings(conn, slug)
    return [Source(b.url, b.kind, b.snapshot_id, b.researched_on.isoformat(), bool(b.archive_key),
                   len(findings.get(canonical_url(b.url), findings.get(b.url, []))))
            for b in baselines], unrecorded


def named(model: Any, step: str) -> Any:
    """`source-check/<step>` in the trace: the judge and the page picker share a model, so a name tells them apart."""
    return model.with_config(metadata={GENERATION_NAME: f"source-check/{step}"})


def free_decision(checks: list[compare.Check], redesign: bool) -> str:
    """Without the judge, a page whose facts all still hold cannot be called minor or changed."""
    if redesign:
        return decision.FULL_PULL
    if any(c.status in decision.ACT_ON for c in checks):
        return decision.REFRESH
    if any(c.status == compare.DIFFERS for c in checks):
        return NEEDS_JUDGE
    return decision.NOTHING


async def run(pool: Any, slug: str, depth: str, refresh: bool, user_id: UUID | None, say: Say = _quiet,
              user_email: str | None = None) -> UUID:
    """Runs one check and saves it whole; the connection is never held while fetching or asking a model.
    `user_email` names the trace's user, as a chat's does."""
    async with pool.connection() as conn:
        given = await load_inputs(conn, slug)
        say(baseline.describe(slug, given.baselines, given.unrecorded))
        if not given.baselines:
            raise NoBaseline(slug)
        run_id = uuid.uuid4()
        # Check and claim under one lock, so two presses at once can't both start a paid run.
        async with conn.transaction():
            await conn.execute(LOCK_SQL, (CHECK_LOCK, slug))
            if await (await conn.execute(BUSY_SQL, (slug,))).fetchone():
                raise Busy(slug)
            await conn.execute(START_SQL, (run_id, slug, depth, user_id))
    settings = get_settings()
    # A check from the Scout screen can come before the first chat turn, which otherwise builds the masked client.
    # Built once, but the first build makes a blocking auth_check, so it runs off the event loop.
    await asyncio.to_thread(configure_langfuse, settings)
    try:
        outcome = await traced_job(
            settings, "sangam_source_check", lambda: _check(pool, run_id, slug, depth, refresh, given, say),
            inputs={"slug": slug, "depth": depth, "refresh": refresh}, session_id=f"source-check-{run_id}",
            tags=("source-check", depth), user_id=user_email or (str(user_id) if user_id else None))
        async with pool.connection() as conn:
            await conn.execute(FINISH_SQL, (outcome["decision"], outcome["refresh_row_id"],
                                            outcome["refresh_summary"], run_id))
    except Exception as exc:
        logger.warning("change check of %s failed", slug, exc_info=True)
        failure = f"{type(exc).__name__}: {exc}"[:500]
        say(f"{slug}: the check failed: {failure}")
        async with pool.connection() as conn:
            await conn.execute(FAIL_SQL, (failure, run_id))
    finally:
        await asyncio.to_thread(flush_traces)  # a blocking upload; the route's answer must not wait on it
    return run_id


async def _check(pool: Any, run_id: UUID, slug: str, depth: str, refresh: bool, given: Inputs,
                 say: Say) -> dict[str, Any]:
    """Every stage, the save and any update; what it returns is the trace's output."""
    # One folder for the run: a document that differed is archived from it before it goes.
    with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
        ended = await stages(slug, depth, Path(scratch), given, say=say)
        assert ended is not None  # no `until`, so every stage ran
        checks, found, verdict = ended
        keys = await save.archive_all(checks, found)
        async with pool.connection() as conn:
            saved = await save.write(conn, run_id, slug, checks, found, keys)
        say(save.describe(slug, run_id, saved))
    row_id, summary = None, None
    if refresh and depth == FULL and verdict == decision.REFRESH:
        row_id, summary = await _refresh(pool, slug, checks, found, given.context, saved)
        say(summary)
    elif refresh:
        say(f"{slug}: no refresh: the decision is {verdict}")
    return {"decision": verdict, "sources": compare.counts(checks), "new_sources": len(found.new),
            "source_checks_rows": saved.rows, "refresh_row_id": row_id, "refresh_summary": summary}


async def stages(slug: str, depth: str, scratch: Path, given: Inputs, until: str | None = None,
                 say: Say = _quiet) -> tuple[list[compare.Check], discover.Discovery, str] | None:
    """Every stage after the baseline, saying what each found; None when it stopped at `until`."""
    today = await fetch_status.fetch_all(given.baselines, scratch)
    say(fetch_status.describe(slug, today))
    if until == "fetch":
        return None
    checks = compare.compare(given.baselines, today)
    say(compare.describe(slug, checks))
    if until == "hash":
        return None
    checks = await diff.run(checks)
    say(diff.describe(slug, checks))
    # Matching every fact against a whole report is CPU work; in a thread it never stalls the server's other requests.
    redesign = await asyncio.to_thread(decision.redesigned, checks)
    if until == "diff":
        return None
    checks = await asyncio.to_thread(evidence.run, checks, given.findings)
    say(evidence.describe(slug, checks))
    if until == "evidence":
        return None
    if depth == FREE:
        found = discover.Discovery(skipped="a free check does not search")
        verdict = free_decision(checks, redesign)
    elif redesign:
        # A full pull rereads everything, so neither the judge nor the search is worth paying for.
        checks = decision.settle(checks)
        found = discover.Discovery(skipped=decision.REDESIGN_REASON)
        say(f"{slug}: judge and discovery skipped: {decision.REDESIGN_REASON}")
        if until == "judge":
            return None
        verdict = decision.FULL_PULL
    else:
        settings = get_settings()
        model = resolve_model(settings.source_check_judge_model)
        checks = await judge.run(checks, given.findings, given.context,
                                 named(model.with_structured_output(judge.Judgement), "judge"))
        say(judge.describe(slug, checks))
        if until == "judge":
            return None
        # Rows saved before snapshots have no baseline, but their cited URLs were read all the same.
        known_urls = {b.url for b in given.baselines} | set(given.findings)
        known_hashes = {b.text_hash for b in given.baselines} | {t.fingerprint for t in today if t.fingerprint}
        async with httpx.AsyncClient() as client:
            found = await discover.run(given.subject, known_urls, known_hashes, given.context,
                                       named(model.with_structured_output(discover.Picks), "discover"),
                                       settings.tavily_api_key,
                                       client, scratch)
        say(discover.describe(slug, found))
        verdict = decision.decide(checks, found, redesign)
    say(decision.describe(slug, checks, found, verdict))
    return checks, found, verdict


async def update_refused(pool: Any, slug: str) -> str | None:
    """Why an update could not be saved today, asked before the judge and the search are paid for; None when it can."""
    async with pool.connection() as conn:
        entity, _rows = await delta.load(conn, slug)
        if entity is None:
            return "Nothing to update: no research of this organisation is on file."
        if await delta.researched_today(conn, slug):
            return ("This organisation was already researched today, and a day holds one research row, "
                    "so an update can be saved from tomorrow.")
    why = delta.cannot_refresh(entity)
    return f"No update: {why}." if why else None


async def _refresh(pool: Any, slug: str, checks: list[compare.Check], found: discover.Discovery,
                   context: judge.Context, saved: save.Saved) -> tuple[int | None, str]:
    """Today's research row from only what changed; it waits in Review & save."""
    settings = get_settings()
    async with pool.connection() as conn:
        entity, rows = await delta.load(conn, slug)
        today = entity is not None and await delta.researched_today(conn, slug)
    if entity is None:
        return None, f"{slug}: no refresh: no research row to carry forward"
    if today:
        return None, f"{slug}: no refresh: it was already researched today"
    if why := delta.cannot_refresh(entity):
        return None, f"{slug}: no refresh: {why}"
    name, kind = entity["canonical_name"] or entity["entity_name"], entity.get("entity_kind")
    srcs = delta.fit(name, delta.sources(checks, found, delta.facts_by_url(rows)), context, kind)
    if not any(s.status != "dead" for s in srcs):
        # A dead page's facts are never removed by a refresh, so a model would be paid to change nothing.
        return None, f"{slug}: no refresh: only gone pages changed, and a person decides whether their facts still hold"
    # Sonnet refuses a forced tool call for structured output, so the delta asks for a JSON schema.
    model = named(resolve_model(settings.research_model).with_structured_output(delta.Delta, method="json_schema"),
                  "delta")
    grader = named(resolve_model(settings.utility_model).with_structured_output(delta.Grade), "grade")
    try:
        proposed, problems = await delta.propose(model, grader, delta.ask(name, srcs, context, kind))
    except Exception as exc:  # noqa: BLE001 — a reply that is no delta saves nothing, and says so
        return None, f"{slug}: refresh not saved: the update model gave no usable delta ({type(exc).__name__})"
    applied = delta.apply(proposed, srcs, kind)
    read = [s.url for s in srcs if s.status != "dead" and s.url not in applied.stale]
    ids = [saved.snapshot_ids[u] for u in read if u in saved.snapshot_ids]
    if not applied.findings and not applied.supersedes:
        async with pool.connection() as conn:
            await delta.note_reread(conn, entity["id"], ids)
        return None, delta.describe(slug, applied, None, problems, nothing=True)
    async with pool.connection() as conn, conn.transaction():
        row_id = await delta.save_row(conn, entity, applied, proposed, context, ids, read)
    return row_id, delta.describe(slug, applied, row_id, problems)
