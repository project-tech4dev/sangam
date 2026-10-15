"""Writing a section: code checks its order and traces every claim to a cited fact, then grades it and saves it."""

from __future__ import annotations

import logging
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.agent.models import resolve_model
from app.core.config import get_settings
from app.db.pool import get_pool
from app.proposals import context, grade, rubric, steps, trace
from app.proposals import facts as fact_rules
from app.proposals import work as work_rules
from app.proposals.tools.proposal_tools import NO_PROPOSAL, require_edit
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

TEXT_LIMIT = 12000
PROBLEMS_SHOWN = 8
_DISTRICTS: set[str] = set()


async def _districts() -> set[str]:
    """Every district Sangam knows, read once: the trace check needs only their names."""
    if not _DISTRICTS:
        async with get_pool().connection() as conn:
            rows = await (await conn.execute("SELECT DISTINCT lower(name) AS name FROM locations WHERE kind = 'district'"
                                             )).fetchall()
        # A three-letter district (Mon, Una, Leh) reads as an ordinary word too often to check.
        _DISTRICTS.update(n for r in rows if r["name"] and len(n := " ".join(r["name"].replace("-", " ").split())) > 3)
    return _DISTRICTS


def _names(p: context.Current) -> set[str]:
    """Partner and people names in the fact list; the proposal's own org and funder are free to name."""
    own = {fact_rules.norm(p.org_name), fact_rules.norm(p.funder_name)}
    return {fact_rules.norm(f.get("value")) for f in (p.work.get("facts") or {}).values()
            if f.get("kind") == "name" and fact_rules.is_live(f) and fact_rules.norm(f.get("value")) not in own}


def _used_in(work: dict[str, Any], code: str, ids: list[str]) -> dict[str, Any]:
    """Each fact's used_in, with this section added where it is cited now and dropped where it no longer is."""
    out = {}
    for k, f in (work.get("facts") or {}).items():
        was = list(f.get("used_in") or [])
        now = sorted({*(c for c in was if c != code), *([code] if k in ids else [])})
        if now != sorted(was):
            out[f"facts.{k}.used_in"] = now
    return out


@tool
async def write_section(code: str, text: str, runtime: ToolRuntime, rev: int = 0) -> str:
    """Save the text of one section of the proposal. Code checks it first and refuses what it cannot trace.

    - Cite a fact as ⟦k7⟧ right after the claim it supports. Every number, amount, place and partner name in a
      paragraph must be in a fact cited in that same paragraph; a year or a Schedule VII clause needs none.
    - Where no fact supports what the section needs, write a gap as [Add: what is missing], for example
      [Add: households food-secure in 2025, with the source].
    - Sections go in order: The Idea's context and problem before its objectives, objectives before the workplan
      and measuring, the workplan before the budget, and the Summary last. The part the person has open on screen
      may be written at any time.
    - Paragraphs are separated by a blank line. Follow the proposal's writing style.

    It returns SAVED with a score from 0 to 2 and what a strong answer still misses, or REFUSED with each claim
    that traced to nothing: cite the fact that holds it, change it to what a cited fact says, or make it a gap.

    Args:
        code: the section's code, for example A3.
        text: the whole text of the section, with ⟦k⟧ citations and [Add: …] gaps.
        rev: the rev read_proposal showed for this section; 0 when it has no text yet.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if refused := require_edit(p):
            return refused
        if early := steps.too_early("write_section", int(p.work.get("stage") or 1)):
            return f"REFUSED: {early}."
        code, text = code.strip(), (text or "").strip()
        section = fact_rules.section_of(p.work, code)
        if section is None:
            return f"REFUSED: this proposal has no section {code!r}."
        if not text or len(text) > TEXT_LIMIT:
            return f"REFUSED: a section's text is 1 to {TEXT_LIMIT:,} characters."
        if not_yet := steps.may_write(p.work, code, context.screen_part(p.work, runtime.state)):
            return f"NOT YET: {not_yet}."
        facts = p.work.get("facts") or {}
        if problems := trace.check(text, facts, districts=await _districts(), names=_names(p)):
            shown = problems[:PROBLEMS_SHOWN] + ([f"and {len(problems) - PROBLEMS_SHOWN} more"]
                                                 if len(problems) > PROBLEMS_SHOWN else [])
            return (f"REFUSED: {section.label} [{code}] was not saved. "
                    + "; ".join(shown)
                    + ". Cite the fact that holds each one, change it to what a cited fact says, or make it a gap.")

        graded = await grade.grade(section, text, resolve_model(get_settings().utility_model))
        ids = trace.cited(text)
        pool = get_pool()
        by = await repo.user_name(pool, p.scope.user_id)

        def change(work: dict, title: str) -> work_rules.Applied:
            changes = {f"sections.{code}.text": text,
                       f"sections.{code}.score": grade.score(graded.missing) if graded else None,
                       **_used_in(work, code, ids)}
            return work_rules.apply(work, changes, {code: rev}, by=by, via="agent", facts=ids,
                                    reason="traced to its facts", title=title)

        try:
            if await repo.save(pool, p.id, change) is None:
                return NO_PROPOSAL
        except work_rules.StaleSection as stale:
            who = (stale.changed_by or {}).get("by", {}).get("name") or "A teammate"
            return (f"REFUSED: {who} changed {section.label} since you read it (now rev "
                    f"{stale.current.get('rev', 0)}). Read it again with read_proposal and build on their text.")
        return _saved(section, text, graded)
    except Exception as exc:
        logger.exception("write_section failed")
        return f"write_section failed: {type(exc).__name__}"


def _saved(section: rubric.Section, text: str, graded: grade.Graded | None) -> str:
    gaps = len(trace.GAP.findall(text))
    out = [f"SAVED {section.label} [{section.code}]."]
    if graded is None:
        out.append("Not graded" + (": it has no strong answer to grade against." if not section.strong
                                   else ": the grader failed; it can be graded on the next save."))
    else:
        score = grade.score(graded.missing)
        out.append(f"Score {score} of 2." + (f" A strong answer still needs: {'; '.join(graded.missing)}."
                                              if graded.missing else ""))
        if score < 2 and section.code in rubric.MUST_SCORE_2:
            out.append(f"{section.label} must score 2: rewrite it once covering what is missing from the facts, "
                       "or mark it as a gap and ask the person.")
    if gaps:
        out.append(f"{gaps} gap{'s' if gaps != 1 else ''} marked [Add: …]: ask about them one at a time.")
    return " ".join(out)
