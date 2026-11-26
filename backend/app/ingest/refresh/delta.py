"""make source-check REFRESH=1: what changed becomes a delta, saved as today's research row for a person to review."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.ingest import brief
from app.ingest.reading.access import canonical_url
from app.ingest.refresh.compare import CHANGED, Check
from app.ingest.refresh.discover import Discovery
from app.ingest.refresh.evidence import BROKEN, UNANCHORED, on_page
from app.ingest.refresh.fetch_status import DEAD
from app.ingest.refresh.judge import DIFF_CHARS, Context, gap_name
from app.ingest.research import source_guards
from app.ingest.research.finding_types import SCHEMA_VERSION, Finding
from app.ingest.research.findings import untiered_org_fact
from app.ingest.research.source_guards import is_private_source

logger = logging.getLogger(__name__)

FINDING: TypeAdapter[Any] = TypeAdapter(Finding)
# The shape goes in the prompt, not the output schema: as a strict grammar it is too large for the API.
PROMPT = ((files("app.ingest") / "prompts" / "research_delta.md").read_text(encoding="utf-8") +
          "\n\nEach finding, as JSON Schema (`concept` picks the kind):\n" +
          json.dumps(FINDING.json_schema(), separators=(",", ":")))
RUBRIC = (files("app.ingest") / "prompts" / "delta_rubric.md").read_text(encoding="utf-8")
PAGE_GONE = "page gone"
REFRESHED = "\n\nRefreshed: "
REFRESH_REASON = "A refresh"  # how a refresh row's stopped_reason starts
NEW_TEXT = 30_000  # a new source's text shown in full up to here; the evidence check still reads all of it
# The whole question; a source past it is left for the next check rather than overflowing the model.
MAX_QUESTION = 150_000

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
        not_found, sources_read, fact_count, goals, schema_version, gaps, years, snapshot_ids, supersedes,
        researched_by, resolved_org_id, resolved_funder_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s,
            %s::jsonb, %s, %s, %s)
    RETURNING id
"""


FINDING_JSON = "the whole finding as one JSON object, in the shape the prompt gives"


class Update(BaseModel):
    id: str
    finding: str = Field(description=FINDING_JSON)


class Removal(BaseModel):
    id: str
    why: str = Field(description="one sentence: what the source now says instead, or that it no longer says it")


class Delta(BaseModel):
    keep: list[str] = Field(default_factory=list)
    update: list[Update] = Field(default_factory=list)
    remove: list[Removal] = Field(default_factory=list)
    add: list[str] = Field(default_factory=list, description=f"each one {FINDING_JSON}")
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
    supersedes: list[dict[str, Any]] = field(default_factory=list)  # brief.superseded of each replaced fact
    refused: list[str] = field(default_factory=list)
    unhandled: list[str] = field(default_factory=list)  # a broken fact no accepted keep, update or remove settled
    stale: set[str] = field(default_factory=set)  # their sources, whose baseline must not move
    kept: int = 0
    updated: int = 0
    removed: int = 0
    added: int = 0


async def load(conn: Any, slug: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The newest research row, which the refresh carries forward, and every row, merged as the brief merges them."""
    row = await (await conn.execute(ENTITY_SQL, (slug,))).fetchone()
    return (dict(row) if row else None), await brief.rows_for(conn, slug)


def cannot_refresh(entity: dict[str, Any]) -> str | None:
    """A refresh carries a row's findings forward, so research that found nothing, or no kind, has none to carry."""
    if entity.get("status") == "not_found":
        return "the newest research found nothing, so there is nothing to update; research it again"
    if entity.get("entity_kind") == "unknown":
        return "the newest research did not settle whether it is a funder or an NGO; research it again"
    return None


async def researched_today(conn: Any, slug: str) -> bool:
    return await (await conn.execute(TODAY_SQL, (slug,))).fetchone() is not None


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
            verdict = PAGE_GONE if c.status == DEAD else verdicts.get((f.get("evidence") or "").strip(), UNANCHORED)
            numbered.append(Fact(f"f{n}", f, verdict))
        out.append(Source(c.baseline.url, "dead" if c.status == DEAD else "changed",
                          "" if c.status == DEAD else c.today.text, tuple(numbered), c.removed, c.added,
                          _hint(c, numbered)))
    for lead, why in found.new:
        if lead.url in found.fetched:
            out.append(Source(lead.url, "new", found.fetched[lead.url].text, hint={"why": why}))
    return out


def _hint(check: Check, numbered: list[Fact]) -> dict[str, Any] | None:
    """The judge numbered this page's evidence sentences 1..n; the delta numbers facts f1..fN across pages."""
    if not check.judgement:
        return None
    hint = {k: v for k, v in check.judgement.items() if k != "affected_findings"}
    sentences = [s for _, s in check.verdicts]
    ids = [f.id for n in check.judgement.get("affected_findings") or [] if 1 <= n <= len(sentences)
           for f in numbered if (f.finding.get("evidence") or "").strip() == sentences[n - 1]]
    if ids:
        hint["affected_facts"] = ids
    return hint


def _cut(lines: tuple[str, ...]) -> list[str]:
    text = "\n".join(lines)
    return [text if len(text) <= DIFF_CHARS else text[:DIFF_CHARS] + "\n… (cut)"]


def ask(name: str, srcs: list[Source], context: Context, kind: str | None = None) -> str:
    """Page text sits in tags the prompt calls data; a changed page shows only its diff unless it has none."""
    blocks = []
    for s in srcs:
        lines = [f'<source status="{s.status}" url="{s.url}">']
        lines += [f"{f.id} [{f.verdict}] {json.dumps(f.finding, ensure_ascii=False)}" for f in s.facts]
        if s.status == "changed" and (s.removed or s.added):
            lines += ["<removed_lines>", *_cut(s.removed), "</removed_lines>",
                      "<added_lines>", *_cut(s.added), "</added_lines>"]
        elif s.status != "dead":
            lines += ["<text>", s.text[:NEW_TEXT], "</text>"]
        if s.hint:
            lines.append(f"hint: {json.dumps(s.hint, ensure_ascii=False)}")
        blocks.append("\n".join([*lines, "</source>"]))
    return (f"Organisation: {name}" + (f" ({kind})" if kind else "") + "\n\n" + "\n\n".join(blocks) +
            f"\n\nFacts Sangam is still missing: {', '.join(context.gaps) or 'none'}"
            f"\nFields Sangam records for this kind of organisation: {', '.join(context.fields) or 'any'}")


def fit(name: str, srcs: list[Source], context: Context, kind: str | None = None) -> list[Source]:
    """The sources one question can hold, in order; the rest wait for the next check, their baselines unmoved."""
    shown: list[Source] = []
    for s in srcs:
        if shown and len(ask(name, [*shown, s], context, kind)) > MAX_QUESTION:
            break
        shown.append(s)
    return shown


async def propose(model: Any, grader: Any, question: str) -> tuple[Delta, list[str]]:
    """The delta, checked once against the rubric and revised once when it fails; a failed grader is no veto."""
    delta: Delta = await model.ainvoke([SystemMessage(PROMPT), HumanMessage(question)])
    if delta is None:  # a refusal or a cut-off reply parses to nothing; the caller reports it and saves nothing
        raise ValueError("no structured answer")
    try:
        grade: Grade = await grader.ainvoke([SystemMessage(RUBRIC),
                                             HumanMessage(f"{question}\n\n<delta>\n{delta.model_dump_json()}\n</delta>")])
        if grade is None:
            raise ValueError("no structured answer")
    except Exception as exc:  # noqa: BLE001 — the code's own checks still run on the delta
        logger.warning("delta grader failed: %s", exc)
        return delta, []
    if grade.passed:
        return delta, []
    fixes = "\n".join(f"- {p}" for p in grade.problems)
    try:
        revised: Delta = await model.ainvoke([SystemMessage(PROMPT), HumanMessage(
            f"{question}\n\nYour last answer:\n{delta.model_dump_json()}\n\nA reviewer found these problems; fix them:"
            f"\n{fixes}")])
        if revised is None:
            raise ValueError("no structured answer")
    except Exception as exc:  # noqa: BLE001 — the first delta still passes the code's own checks
        logger.warning("delta revision failed: %s", exc)
        return delta, [*grade.problems, f"the revision failed ({type(exc).__name__}), so the first answer stands"]
    return revised, grade.problems


def apply(delta: Delta, srcs: list[Source], kind: str | None = None) -> Applied:
    """The delta as findings and the facts they replace; anything citing a sentence not on its source, or that a
    research save would refuse for this kind of organisation, is refused."""
    facts = {f.id: f for s in srcs for f in s.facts}
    # A changed page is quoted from what it added, so an old, unchanged sentence cannot pass as new.
    texts = {s.url: "\n".join(s.added) if s.status == "changed" and s.added else s.text for s in srcs if s.text}
    out, seen = Applied(), set()

    def known(fact_id: str, verb: str) -> Fact | None:
        if fact_id not in facts or fact_id in seen:
            out.refused.append(f"{verb} {fact_id}: not an id given, or used twice")
            return None
        seen.add(fact_id)
        return facts[fact_id]

    def parsed(raw: str, verb: str) -> dict[str, Any] | None:
        try:
            finding = FINDING.validate_python(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            out.refused.append(f"{verb}: not a valid finding ({str(exc).splitlines()[0][:160]})")
            return None
        # The checks save_research runs, so a refresh cannot save what research could not.
        wrong = source_guards.check_research([finding], kind)
        if kind == "org" and untiered_org_fact(finding):
            wrong.append(f"an org's {finding.concept} finding needs source_type and evidence_tier")
        if wrong:
            out.refused.append(f"{verb}: {'; '.join(wrong)[:200]}")
            return None
        return FINDING.dump_python(finding, mode="json")

    def quoted(finding: dict[str, Any], verb: str) -> bool:
        url = canonical_url(finding["source_url"])
        if url in texts and on_page(finding["evidence"], texts[url]):
            return True
        out.refused.append(f"{verb} {finding.get('concept')}: its sentence is not on {url}")
        return False

    settled: set[str] = set()
    for fact_id in delta.keep:
        if known(fact_id, "keep") is not None:
            out.kept += 1
            settled.add(fact_id)
    for u in delta.update:
        if ((old := known(u.id, "update")) and (new := parsed(u.finding, f"update {u.id}"))
                and quoted(new, f"update {u.id} →")):
            out.supersedes.append(brief.superseded(old.finding))
            out.findings.append(new)
            out.updated += 1
            settled.add(u.id)
    for r in delta.remove:
        if (old := known(r.id, "remove")) and old.verdict == PAGE_GONE:
            # A page moving is not the fact ending; a person decides that in Review & save.
            out.refused.append(f"remove {r.id}: its page is gone, which does not end the fact")
        elif old:
            out.supersedes.append(brief.superseded(old.finding))
            out.removed += 1
            settled.add(r.id)
    # A broken fact left as it was would be read as current once its page's baseline moved on.
    for s in srcs:
        for f in s.facts:
            if f.verdict == BROKEN and f.id not in settled:
                out.unhandled.append(f.id)
                out.stale.add(s.url)
    for a in delta.add:
        if (new := parsed(a, "add")) and quoted(new, "add"):
            out.findings.append(new)
            out.added += 1
    return out


async def save_row(conn: Any, entity: dict[str, Any], applied: Applied, delta: Delta, context: Context,
                   snapshot_ids: list[int], sources_read: list[str]) -> int | None:
    """Today's row, carrying the newest row's frame forward; None when the entity was already researched today."""
    if await researched_today(conn, entity["slug"]):  # the race guard; _refresh asked before paying for a model
        return None
    # The model's word closes nothing: a gap closes only when an accepted finding fills it.
    closed = set(delta.gaps_closed) & set(context.gaps)
    gaps = [g for g in _list(entity.get("gaps"))
            if g.get("concept") and not (gap_name(g) in closed and _fills(g, applied.findings))]
    found = {f.get("concept") for f in applied.findings}
    base = (entity["summary"] or "").split(REFRESHED)[0]  # one refresh note, not one per refresh
    summary = f"{base}{REFRESHED}{delta.summary}"
    reason = f"{REFRESH_REASON}: {len(sources_read)} changed or new sources reread; the rest stand from earlier research."
    # Private findings were never offered for review, so they stand: the brief still hides a summary they
    # informed, and promotion, which reads them from the newest row, still sees them.
    private = [f for f in _list(entity.get("findings")) if is_private_source(f.get("source_url"))]
    findings = [*applied.findings, *private]
    row = await (await conn.execute(INSERT_SQL, (
        entity["entity_name"], entity.get("canonical_name"), entity["entity_kind"], entity["slug"],
        entity.get("website"), entity.get("status") or "complete", reason, summary, json.dumps(findings),
        [c for c in entity.get("not_found") or [] if c not in found], sources_read, len(findings),
        json.dumps(_list(entity.get("goals"))), SCHEMA_VERSION, json.dumps(gaps),
        entity.get("years") or [], snapshot_ids, json.dumps(applied.supersedes),
        entity.get("researched_by"), entity.get("resolved_org_id"), entity.get("resolved_funder_id"),
    ))).fetchone()
    return row["id"]


def _fills(gap: dict[str, Any], findings: list[dict[str, Any]]) -> bool:
    """Its concept, its field when it names one, and its year when it names one."""
    return any(f.get("concept") == gap["concept"]
               and (not gap.get("field") or f.get(gap["field"]) not in (None, "", [], {}))
               and (not gap.get("fiscal_year") or f.get("fiscal_year") == gap["fiscal_year"])
               for f in findings)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else json.loads(value or "[]")


def describe(slug: str, applied: Applied, row_id: int | None, problems: list[str], nothing: bool = False) -> str:
    counts = (f"{applied.kept} kept · {applied.updated} updated · {applied.removed} removed · "
              f"{applied.added} added")
    if nothing:
        head = f"{slug}: refresh not saved: the delta changes nothing ({counts})"
    elif row_id:
        head = f"{slug}: refresh saved as entity_research #{row_id} ({counts}); it waits in Review & save"
    else:
        head = f"{slug}: refresh not saved: it was already researched today ({counts})"
    lines = [head]
    lines += [f"  reviewer: {p}" for p in problems]
    lines += [f"  refused: {r}" for r in applied.refused]
    if applied.unhandled:
        lines.append(f"  not settled: {', '.join(applied.unhandled)} broken and not updated or removed; "
                     f"{', '.join(sorted(applied.stale))} keep their old version, so the next check flags them again")
    return "\n".join(lines)
