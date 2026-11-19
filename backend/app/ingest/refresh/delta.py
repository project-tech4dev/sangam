"""make source-check REFRESH=1: what changed becomes a delta, saved as today's research row for a person to review."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.ingest import brief
from app.ingest.reading.access import canonical_url
from app.ingest.refresh.compare import CHANGED, Check
from app.ingest.refresh.discover import Discovery
from app.ingest.refresh.evidence import UNANCHORED, on_page
from app.ingest.refresh.fetch_status import DEAD
from app.ingest.refresh.judge import Context, gap_name
from app.ingest.research.finding_types import SCHEMA_VERSION, Finding
from app.ingest.research.source_guards import is_private_source

logger = logging.getLogger(__name__)

PROMPT = (files("app.ingest") / "prompts" / "research_delta.md").read_text(encoding="utf-8")
RUBRIC = (files("app.ingest") / "prompts" / "delta_rubric.md").read_text(encoding="utf-8")
NEW_TEXT = 30_000  # a new source's text shown in full up to here; the evidence check still reads all of it

ENTITY_SQL = """
    SELECT * FROM entity_research
     WHERE slug = %s AND status <> 'wrong_entity'
     ORDER BY researched_on DESC, id DESC
     LIMIT 1
"""
TODAY_SQL = "SELECT 1 FROM entity_research WHERE slug = %s AND researched_on = current_date"
INSERT_SQL = """
    INSERT INTO entity_research (
        entity_name, canonical_name, entity_kind, slug, website, status, stopped_reason, summary, findings,
        not_found, sources_read, fact_count, goals, schema_version, gaps, years, snapshot_ids, supersedes)
    VALUES (%s, %s, %s, %s, %s, 'complete', %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s,
            %s::jsonb)
    RETURNING id
"""


class Update(BaseModel):
    id: str
    finding: Finding


class Removal(BaseModel):
    id: str
    why: str = Field(description="one sentence: what the source now says instead, or that it no longer says it")


class Delta(BaseModel):
    keep: list[str] = Field(default_factory=list)
    update: list[Update] = Field(default_factory=list)
    remove: list[Removal] = Field(default_factory=list)
    add: list[Finding] = Field(default_factory=list)
    gaps_closed: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=20, description="two or three sentences on what changed")


class Grade(BaseModel):
    passed: bool
    problems: list[str] = Field(default_factory=list, description="one line per failed criterion")


@dataclass(frozen=True)
class Fact:
    id: str
    finding: dict[str, Any]
    verdict: str  # intact, broken or unanchored, from the evidence check; "page gone" on a dead source


@dataclass(frozen=True)
class Source:
    url: str
    status: str  # changed, dead or new
    text: str  # today's text, what an update or add must quote; empty for a dead page
    facts: tuple[Fact, ...] = ()
    removed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    hint: dict[str, Any] | None = None


@dataclass
class Applied:
    findings: list[dict[str, Any]] = field(default_factory=list)
    supersedes: list[list[str]] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    kept: int = 0
    updated: int = 0
    removed: int = 0
    added: int = 0


async def load(conn: Any, slug: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The newest research row, which the refresh carries forward, and every row, merged as the brief merges them."""
    row = await (await conn.execute(ENTITY_SQL, (slug,))).fetchone()
    return (dict(row) if row else None), await brief.rows_for(conn, slug)


def facts_by_url(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every public fact the brief holds, by the source it cites."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in brief.merge_findings(rows):
        url = f.get("source_url")
        if url and not is_private_source(url):
            out.setdefault(canonical_url(url), []).append(f)
    return out


def sources(checks: list[Check], found: Discovery, facts: dict[str, list[dict[str, Any]]]) -> list[Source]:
    """What the updater reads: each changed or dead source with its facts numbered, then each new source."""
    out: list[Source] = []
    n = 0
    for c in checks:
        if c.status not in (CHANGED, DEAD):
            continue
        verdicts = {sentence: v for v, sentence in c.verdicts}
        numbered = []
        for f in facts.get(c.baseline.url, []):
            n += 1
            verdict = "page gone" if c.status == DEAD else verdicts.get((f.get("evidence") or "").strip(), UNANCHORED)
            numbered.append(Fact(f"f{n}", f, verdict))
        out.append(Source(c.baseline.url, "dead" if c.status == DEAD else "changed",
                          "" if c.status == DEAD else c.today.text, tuple(numbered), c.removed, c.added, c.judgement))
    for lead, why in found.new:
        if lead.url in found.fetched:
            out.append(Source(lead.url, "new", found.fetched[lead.url].text, hint={"why": why}))
    return out


def ask(name: str, srcs: list[Source], context: Context) -> str:
    """Page text sits in tags the prompt calls data; a changed page shows only its diff unless it has none."""
    blocks = []
    for s in srcs:
        lines = [f'<source status="{s.status}" url="{s.url}">']
        lines += [f"{f.id} [{f.verdict}] {json.dumps(f.finding, ensure_ascii=False)}" for f in s.facts]
        if s.status == "changed" and (s.removed or s.added):
            lines += ["<removed_lines>", *s.removed, "</removed_lines>", "<added_lines>", *s.added, "</added_lines>"]
        elif s.status != "dead":
            lines += ["<text>", s.text[:NEW_TEXT], "</text>"]
        if s.hint:
            lines.append(f"hint: {json.dumps(s.hint, ensure_ascii=False)}")
        blocks.append("\n".join([*lines, "</source>"]))
    return (f"Organisation: {name}\n\n" + "\n\n".join(blocks) +
            f"\n\nFacts Sangam is still missing: {', '.join(context.gaps) or 'none'}"
            f"\nFields Sangam records for this kind of organisation: {', '.join(context.fields) or 'any'}")


async def propose(model: Any, grader: Any, question: str) -> tuple[Delta, list[str]]:
    """The delta, checked once against the rubric and revised once when it fails; a failed grader is no veto."""
    delta: Delta = await model.ainvoke([SystemMessage(PROMPT), HumanMessage(question)])
    try:
        grade: Grade = await grader.ainvoke([SystemMessage(RUBRIC),
                                             HumanMessage(f"{question}\n\n<delta>\n{delta.model_dump_json()}\n</delta>")])
    except Exception as exc:  # noqa: BLE001 — the code's own checks still run on the delta
        logger.warning("delta grader failed: %s", exc)
        return delta, []
    if grade.passed:
        return delta, []
    fixes = "\n".join(f"- {p}" for p in grade.problems)
    revised: Delta = await model.ainvoke([SystemMessage(PROMPT), HumanMessage(
        f"{question}\n\nYour last answer:\n{delta.model_dump_json()}\n\nA reviewer found these problems; fix them:\n{fixes}")])
    return revised, grade.problems


def apply(delta: Delta, srcs: list[Source], context: Context) -> Applied:
    """The delta as findings and the facts they replace; anything citing a sentence not on its source is refused."""
    facts = {f.id: f for s in srcs for f in s.facts}
    texts = {s.url: s.text for s in srcs if s.text}
    out, seen = Applied(), set()

    def known(fact_id: str, verb: str) -> Fact | None:
        if fact_id not in facts or fact_id in seen:
            out.refused.append(f"{verb} {fact_id}: not an id given, or used twice")
            return None
        seen.add(fact_id)
        return facts[fact_id]

    def quoted(finding: dict[str, Any], verb: str) -> bool:
        url = canonical_url(finding["source_url"])
        if url in texts and on_page(finding["evidence"], texts[url]):
            return True
        out.refused.append(f"{verb} {finding.get('concept')}: its sentence is not on {url}")
        return False

    for fact_id in delta.keep:
        out.kept += known(fact_id, "keep") is not None
    for u in delta.update:
        if (old := known(u.id, "update")) and quoted(new := u.finding.model_dump(mode="json"), f"update {u.id} →"):
            out.supersedes.append(list(brief.fact_key(old.finding)))
            out.findings.append(new)
            out.updated += 1
    for r in delta.remove:
        if old := known(r.id, "remove"):
            out.supersedes.append(list(brief.fact_key(old.finding)))
            out.removed += 1
    for a in delta.add:
        if quoted(new := a.model_dump(mode="json"), "add"):
            out.findings.append(new)
            out.added += 1
    return out


async def save_row(conn: Any, entity: dict[str, Any], applied: Applied, delta: Delta, context: Context,
                   snapshot_ids: list[int], sources_read: list[str]) -> int | None:
    """Today's row, carrying the newest row's frame forward; None when the entity was already researched today."""
    if await (await conn.execute(TODAY_SQL, (entity["slug"],))).fetchone():
        return None
    closed = set(delta.gaps_closed) & set(context.gaps)
    gaps = [g for g in _list(entity.get("gaps")) if g.get("concept") and gap_name(g) not in closed]
    found = {f.get("concept") for f in applied.findings}
    summary = f"{entity['summary']}\n\nRefreshed: {delta.summary}"
    reason = f"A refresh: {len(sources_read)} changed or new sources reread; the rest stand from earlier research."
    row = await (await conn.execute(INSERT_SQL, (
        entity["entity_name"], entity.get("canonical_name"), entity["entity_kind"], entity["slug"],
        entity.get("website"), reason, summary, json.dumps(applied.findings),
        [c for c in entity.get("not_found") or [] if c not in found], sources_read, len(applied.findings),
        json.dumps(_list(entity.get("goals"))), SCHEMA_VERSION, json.dumps(gaps),
        entity.get("years") or [], snapshot_ids, json.dumps(applied.supersedes),
    ))).fetchone()
    return row["id"]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else json.loads(value or "[]")


def describe(slug: str, applied: Applied, row_id: int | None, problems: list[str]) -> str:
    counts = (f"{applied.kept} kept · {applied.updated} updated · {applied.removed} removed · "
              f"{applied.added} added")
    head = (f"{slug}: refresh saved as entity_research #{row_id} ({counts}); it waits in Review & save"
            if row_id else f"{slug}: refresh not saved: it was already researched today ({counts})")
    lines = [head]
    lines += [f"  reviewer: {p}" for p in problems]
    lines += [f"  refused: {r}" for r in applied.refused]
    return "\n".join(lines)
