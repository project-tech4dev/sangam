"""The proposal itself: read any part of it, and move to the next step when code says nothing is missing."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.db.pool import get_pool
from app.proposals import context, rubric, steps
from app.proposals import facts as fact_rules
from app.proposals import work as work_rules
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

NO_PROPOSAL = "No proposal is open in this chat."
READ_ONLY = "REFUSED: you can read this proposal; only its organisation's admins and stewards and the Sangam team change it."
PARTS = ("requirements", "form", "documents", "style", "facts")


def require_edit(p: context.Current) -> str | None:
    """Every tool that changes the proposal asks this first; the screen's buttons are not the check."""
    return None if p.can_edit else READ_ONLY


async def _documents(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    async with get_pool().connection() as conn:
        return await (await conn.execute(
            "SELECT id, title, doc_type, as_of FROM documents WHERE id = ANY(%s) ORDER BY id", (ids,)
        )).fetchall()


def _fact_lines(facts: dict[str, Any], code: str | None = None) -> list[str]:
    """Each live fact with the id write_section cites it by, its standing and its source."""
    lines = []
    for k, f in facts.items():
        if fact_rules.is_live(f) and (code is None or f.get("section") == code):
            when = f" ({f['as_of']})" if f.get("as_of") else ""
            where = f.get("source_name") or f.get("marker") or f.get("source_url") or f.get("origin")
            lines.append(f"- {k} · {f.get('subject')}: {f.get('value')}{when} · {f.get('status')}, {f.get('origin')} · {where}")
    return lines


def _section(s: rubric.Section, saved: dict[str, Any], whole: bool, facts: dict[str, Any] | None = None) -> list[str]:
    text = (saved.get("text") or "").strip()
    state = "finished" if saved.get("done") else ("draft" if text else "empty")
    lines = [f"### {s.label} [{s.code}] · {state}" + (f" · score {saved['score']} of 2" if saved.get("score") is not None else "")
             + (" · NEEDS REWRITING: it cites a fact that was corrected or set aside" if saved.get("needs_rewrite") else ""),
             f"Asks: {s.question}"]
    if whole:
        lines += [f"A strong answer holds: {'; '.join(s.strong)}" if s.strong else "",
                  f"A weak answer: {s.weak}" if s.weak else "",
                  f"Text (rev {saved.get('rev', 0)}):\n{text}" if text else "No text yet (rev 0).",
                  "Facts for this part:\n" + "\n".join(_fact_lines(facts or {}, s.code) or ["- none yet"])]
    else:
        lines.append(f"{len(text.split())} words" if text else "No text yet.")
    return [line for line in lines if line]


@tool
async def read_proposal(part: str = "") -> str:
    """Read this chat's proposal: the whole outline, or one part of it in full.

    Leave `part` empty for the outline: the step, the requirements and answers, the form, the documents
    Sangam may read, the style, and each section's state. Pass a tab (idea, project, people, ask_risk,
    why_you) for its sections in full with their facts, a section's code (for example A3) for that section,
    "facts" for every fact in use with the id write_section cites, or one of requirements, form, documents, style.

    Args:
        part: empty, a tab key, a section code, facts, or requirements / form / documents / style.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        work, part = p.work, part.strip()
        saved = work.get("sections") or {}
        facts = work.get("facts") or {}
        all_sections = context.sections(work)
        tabs = {key: label for key, label, _ in rubric.TABS}
        stage = int(work.get("stage") or 1)

        if part in tabs:
            chosen = [s for s in all_sections if s.tab == part]
            return "\n\n".join([f"## {tabs[part]}", *["\n".join(_section(s, saved.get(s.code) or {}, True, facts))
                                                     for s in chosen]])
        if section := next((s for s in all_sections if s.code == part), None):
            return "\n".join(_section(section, saved.get(section.code) or {}, True, facts))
        if part and part not in PARTS:
            return f"No part {part!r}. Use a tab ({', '.join(tabs)}), a section code, or one of {', '.join(PARTS)}."

        if part == "facts":
            return "\n".join(["Every fact in use, cited by its id:", *(_fact_lines(facts) or ["- none yet"])])
        out: list[str] = []
        if part in ("", "requirements"):
            out.append("\n".join(["What the funder requires:", *context.requirements(work)]))
        if part in ("", "form"):
            out.append(f"Form: {context.form(work)}")
        if part in ("", "documents"):
            docs = await _documents(work.get("sources") or [])
            out.append("Documents Sangam may read: " + ("none ticked" if not docs else "; ".join(
                f"document {d['id']} · {d['title'] or 'untitled'} · {d['doc_type'] or 'file'}"
                + (f" · {d['as_of']}" if d["as_of"] else "") for d in docs)))
        if part in ("", "style"):
            out.append(f"Writing style: {(work.get('style') or '').strip() or 'not set'}")
        if part == "":
            out.insert(0, f"Step {stage} of 4: {steps.STAGES.get(stage, '')}")
            for key, label, _ in rubric.TABS:
                out.append(f"## {label} ({key})")
                out += ["\n".join(_section(s, saved.get(s.code) or {}, False)) for s in all_sections if s.tab == key]
        return "\n\n".join(out)
    except Exception as exc:
        logger.exception("read_proposal failed")
        return f"read_proposal failed: {type(exc).__name__}"


@tool
async def advance_step() -> str:
    """Move the proposal to its next step. Code checks first and refuses, with what is missing, until nothing is.

    Call it only when the person wants to go on; the answers themselves are given on screen.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if refused := require_edit(p):
            return refused
        by = await repo.user_name(get_pool(), p.scope.user_id)
        missing: list[str] = []

        def change(work: dict, title: str) -> work_rules.Applied | None:
            stage = int(work.get("stage") or 1)
            missing.extend(steps.exit_check(stage, work))
            if missing:
                raise _NotYet
            return work_rules.apply(work, {"stage": stage + 1}, by=by, via="agent",
                                    reason="the person asked to go on", title=title, advance=True)

        try:
            applied = await repo.save(get_pool(), p.id, change)
        except _NotYet:
            return f"NOT YET: to leave this step, {'; '.join(missing)}."
        if applied is None:
            return NO_PROPOSAL
        stage = applied.work["stage"]
        return f"Moved to step {stage} of 4: {steps.STAGES[stage]}."
    except Exception as exc:
        logger.exception("advance_step failed")
        return f"advance_step failed: {type(exc).__name__}"


class _NotYet(Exception):
    pass
