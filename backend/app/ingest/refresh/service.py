"""The change check run from the Scout screen: the same stages as make source-check, every result saved."""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from app.agentkit.models import resolve_model
from app.core.config import get_settings
from app.ingest import brief
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

logger = logging.getLogger(__name__)

FREE, FULL = "free", "full"
NEEDS_JUDGE = "needs the judge"  # a free run that found a page differing with every fact still on it
STALE_MINUTES = 30  # a run unfinished after this long died with its request; another may start

BUSY_SQL = f"""
    SELECT 1 FROM source_check_runs
     WHERE slug = %s AND finished_at IS NULL AND started_at > now() - interval '{STALE_MINUTES} minutes'
"""
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


def free_decision(checks: list[compare.Check], redesign: bool) -> str:
    """Without the judge, a page whose facts all still hold cannot be called minor or changed."""
    if redesign:
        return decision.FULL_PULL
    if any(c.status in decision.ACT_ON for c in checks):
        return decision.REFRESH
    if any(c.status == compare.DIFFERS for c in checks):
        return NEEDS_JUDGE
    return decision.NOTHING


async def run(pool: Any, slug: str, depth: str, refresh: bool, user_id: UUID | None) -> UUID:
    """Runs one check and saves it whole; the connection is never held while fetching or asking a model."""
    async with pool.connection() as conn:
        baselines, _unrecorded = await baseline.load(conn, slug)
        if not baselines:
            raise NoBaseline(slug)
        if await (await conn.execute(BUSY_SQL, (slug,))).fetchone():
            raise Busy(slug)
        findings = await evidence.load_findings(conn, slug)
        context = await judge.load_context(conn, slug)
        subject = await discover.load_subject(conn, slug)
        run_id = uuid.uuid4()
        await conn.execute(START_SQL, (run_id, slug, depth, user_id))
    try:
        with tempfile.TemporaryDirectory(prefix="source-check-") as scratch:
            checks, found, verdict = await _stages(depth, Path(scratch), baselines, findings, context, subject)
            keys = await save.archive_all(checks, found)
            async with pool.connection() as conn:
                saved = await save.write(conn, run_id, slug, checks, found, keys)
        row_id, summary = None, None
        if refresh and depth == FULL and verdict == decision.REFRESH:
            row_id, summary = await _refresh(pool, slug, checks, found, context, saved)
        async with pool.connection() as conn:
            await conn.execute(FINISH_SQL, (verdict, row_id, summary, run_id))
    except Exception as exc:
        logger.warning("change check of %s failed", slug, exc_info=True)
        async with pool.connection() as conn:
            await conn.execute(FAIL_SQL, (f"{type(exc).__name__}: {exc}"[:500], run_id))
    return run_id


async def _stages(depth: str, scratch: Path, baselines: list[baseline.Baseline], findings: dict[str, list[str]],
                  context: judge.Context, subject: discover.Subject | None
                  ) -> tuple[list[compare.Check], discover.Discovery, str]:
    today = [await fetch_status.fetch_today(b, scratch) for b in baselines]
    checks = compare.compare(baselines, today)
    redesign = decision.redesigned(checks)
    checks = evidence.run(await diff.run(checks), findings)
    if depth == FREE:
        return checks, discover.Discovery(skipped="a free check does not search"), free_decision(checks, redesign)
    if redesign:
        # A full pull rereads everything, so neither the judge nor the search is worth paying for.
        return decision.settle(checks), discover.Discovery(skipped=decision.REDESIGN_REASON), decision.FULL_PULL
    settings = get_settings()
    model = resolve_model(settings.source_check_judge_model)
    checks = await judge.run(checks, findings, context, model.with_structured_output(judge.Judgement))
    known_urls = {b.url for b in baselines}
    known_hashes = {b.text_hash for b in baselines} | {t.fingerprint for t in today if t.fingerprint}
    async with httpx.AsyncClient() as client:
        found = await discover.run(subject, known_urls, known_hashes, context,
                                   model.with_structured_output(discover.Picks), settings.tavily_api_key,
                                   client, scratch)
    return checks, found, decision.decide(checks, found, redesign)


async def _refresh(pool: Any, slug: str, checks: list[compare.Check], found: discover.Discovery,
                   context: judge.Context, saved: save.Saved) -> tuple[int | None, str]:
    """Today's research row from only what changed; it waits in Review & save."""
    settings = get_settings()
    async with pool.connection() as conn:
        entity, rows = await delta.load(conn, slug)
    if entity is None:
        return None, "no research row to carry forward"
    srcs = delta.sources(checks, found, delta.facts_by_url(rows))
    # Sonnet refuses a forced tool call for structured output, so the delta asks for a JSON schema.
    model = resolve_model(settings.research_model).with_structured_output(delta.Delta, method="json_schema")
    grader = resolve_model(settings.utility_model).with_structured_output(delta.Grade)
    proposed, problems = await delta.propose(
        model, grader, delta.ask(entity["canonical_name"] or entity["entity_name"], srcs, context))
    applied = delta.apply(proposed, srcs, context)
    read = [s.url for s in srcs if s.status != "dead"]
    async with pool.connection() as conn:
        async with conn.transaction():
            row_id = await delta.save_row(conn, entity, applied, proposed, context,
                                          [saved.snapshot_ids[u] for u in read if u in saved.snapshot_ids], read)
        history = await brief.rows_for(conn, slug) if row_id else []
    if history:
        try:
            await brief.publish(history)
        except Exception:  # the row is saved; the brief catches up on the next save
            logger.warning("brief for %s not republished after the refresh", slug, exc_info=True)
    return row_id, delta.describe(slug, applied, row_id, problems)
