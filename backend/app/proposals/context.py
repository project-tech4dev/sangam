"""What the proposal agent knows each turn: the run's proposal, read fresh, and the two blocks told to the model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.security import CallerScope, chat_proposal, chat_scope
from app.db.pool import get_pool
from app.proposals import readiness, rubric, steps
from app.repositories import proposals as repo

SCREEN = "What the person is looking at"  # the screen's useAgentContext description; the frontend uses the same words
SCREEN_TEXT = 600  # a selection longer than this is cut
OTHERS_SHOWN = 5  # teammates' latest changes told to the model


@dataclass(frozen=True)
class Current:
    id: int
    title: str
    org_id: int
    org_name: str
    funder_id: int
    funder_name: str
    work: dict[str, Any]
    scope: CallerScope
    can_edit: bool


async def current() -> Current | None:
    """This run's proposal, read again on every call: the screen saves between tool calls."""
    proposal_id, scope = chat_proposal.get(), chat_scope.get()
    if proposal_id is None or scope is None:
        return None
    row = await repo.load(get_pool(), proposal_id)
    if row is None:
        return None
    work = row["work"] or {}
    return Current(id=row["id"], title=row["title"], org_id=row["org_id"], org_name=row["org_name"],
                   funder_id=row["funder_id"], funder_name=row["funder_name"], work=work, scope=scope,
                   can_edit=scope.can_edit_proposal(row["org_id"]))


def sections(work: dict[str, Any]) -> list[rubric.Section]:
    return rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))


ANSWER_WORDS = {"yes": "yes", "will_have": "will have it before sending", "no": "no"}


def requirements(work: dict[str, Any]) -> list[str]:
    gates = work.get("gates") or {}
    return [f"- {r['label']}{' (the funder needs it)' if r.get('hard') else ''}: "
            f"{ANSWER_WORDS.get(gates.get(r['key']), 'not answered yet')}" for r in work.get("requirements") or []]


def form(work: dict[str, Any]) -> str:
    template = work.get("template")
    if template:
        return f"the funder's own form (document {template['document_id']})" if template.get("document_id") \
            else "the funder's own form"
    return "Sangam's usual order" if work.get("skipped_template") else "not chosen yet"


def stable(p: Current) -> str:
    """The part that changes only when the proposal does: cached. Names, steps and states only; no record text."""
    stage = int(p.work.get("stage") or 1)
    saved = p.work.get("sections") or {}
    def state(part: dict[str, Any]) -> str:
        word = "finished" if part.get("done") else "draft" if part.get("text") else "empty"
        return (word + (f", score {part['score']} of 2" if part.get("score") is not None else "")
                + (", NEEDS REWRITING: a fact it cites was corrected or set aside" if part.get("needs_rewrite") else ""))

    states = [f"{s.label} [{s.code}]: {state(saved.get(s.code) or {})}" for s in sections(p.work)]
    return "\n".join([
        "## This proposal",
        f"\"{p.title}\": {p.org_name} [org:{p.org_id}] asking {p.funder_name} [funder:{p.funder_id}].",
        f"Step {stage} of 4: {steps.STAGES.get(stage, '')}.",
        "What the funder requires, and the answers so far:", *requirements(p.work),
        f"Form: {form(p.work)}.",
        "Sections:", *states,
    ])


def _screen(state: Any) -> dict[str, Any]:
    def field(item: Any, key: str) -> Any:
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    items = field((state or {}).get("ag-ui") or {}, "context") or []
    value = next((field(c, "value") for c in items if field(c, "description") == SCREEN), None)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _what(work: dict[str, Any], entry: dict[str, Any]) -> str:
    """A log entry's change in words: sections and requirements by label, facts and questions by subject."""
    head, _, rest = entry["path"].partition(".")
    if head == "sections":
        code, _, field = rest.partition(".")
        label = next((s.label for s in sections(work) if s.code == code), code)
        return f"{label} [{code}]" + {"done": " (marked finished or not)", "score": " (its score)",
                                      "needs_rewrite": " (marked for rewriting)"}.get(field, "")
    if head == "gates":
        return next((r["label"] for r in work.get("requirements") or [] if r["key"] == rest), "a requirement")
    if head in ("facts", "questions"):
        key, _, field = rest.partition(".")
        item = (work.get(head) or {}).get(key) or {}
        subject = item.get("subject") or "a fact"
        if head == "questions":
            return f"the question about {subject}"
        return {"status": f"{subject} (set to {entry.get('to')})",
                "used_in": f"where {subject} is cited"}.get(field, f"{subject} (added)")
    if head == "readers":
        title, _, status = str(entry.get("to") or "").rpartition(": ")
        return f"the reading of {title or 'a file'} ({status})"
    return {"stage": "the step", "template": "the form", "skipped_template": "the form", "sources": "the files to read",
            "style": "the writing style", "title": "the title"}.get(head, head)


def outside(p: Current) -> list[str]:
    """Changes this chat did not make, newest first: teammates' and the person's own clicks on screen."""
    me = str(p.scope.user_id) if p.scope.user_id else None
    theirs = [e for e in reversed(p.work.get("log") or [])
              if str((e.get("by") or {}).get("id")) != me or e.get("via") != "agent"]
    return [f"- {'The person, on screen,' if str((e.get('by') or {}).get('id')) == me else (e.get('by') or {}).get('name') or 'Someone'} changed "
            f"{_what(p.work, e)}, "
            f"{str(e.get('at', ''))[:16].replace('T', ' ')} UTC" for e in theirs[:OTHERS_SHOWN]]


def screen_part(work: dict[str, Any], state: Any) -> str | None:
    """The section code on screen; one the server does not know is dropped."""
    code = _screen(state).get("part")
    return code if isinstance(code, str) and any(s.code == code for s in sections(work)) else None


def waiting(p: Current) -> list[str]:
    """The open and parked questions, by whom, and the facts nobody has checked yet."""
    me = str(p.scope.user_id) if p.scope.user_id else None
    labels = {s.code: s.label for s in sections(p.work)}
    lines = []
    for k, q in (p.work.get("questions") or {}).items():
        where = labels.get(q.get("section"), "the proposal")
        who = q.get("asked_of") or {}
        if q.get("status") == "open":
            lines.append(f"- {k} {where}, {q.get('subject')}: " + (
                "asked of this person, waiting for their answer" if str(who.get("id")) == me
                else f"asked of {who.get('name') or 'a teammate'}, waiting; do not ask it again"))
        elif q.get("status") == "parked":
            lines.append(f"- {k} {where}, {q.get('subject')}: saved for later by whoever was asked; ask it of this person "
                         f"only while {where} is the part open on their screen")
    unchecked = sum(1 for f in (p.work.get("facts") or {}).values() if f.get("status") == "proposed")
    if unchecked:
        lines.append(f"- {unchecked} fact{'s' if unchecked != 1 else ''} not yet confirmed by anyone")
    return lines


def reading(work: dict[str, Any]) -> list[str]:
    """Each reader's outcome, so a "why is this file not in the facts?" has its answer."""
    out = []
    for r in (work.get("readers") or {}).values():
        status = r.get("status")
        what = {"done": "read", "running": f"being read, started by {(r.get('by') or {}).get('name') or 'a teammate'}",
                "failed": f"could not be read: {r.get('error') or 'no reason given'}"}.get(status, status)
        out.append(f"- {r.get('title') or 'a file'}: {what}")
    return out


def on_screen(p: Current, state: Any) -> str:
    """Where the person is as they send: the step, and the part they have open."""
    screen = _screen(state)
    part = screen_part(p.work, state)
    labels = {s.code: s.label for s in sections(p.work)}
    where = [f"step {screen['step']}"] if screen.get("step") else []
    if part:
        where.append(f"part {labels[part]} [{part}]")
    if not where:
        return "On screen now: not known."
    return "On screen now: " + ", ".join(where) + "." + ("" if part else " No part is open.")


def live(p: Current, state: Any) -> str:
    """The part that changes every turn: what is missing, who is asking, and where they are on screen. Never saved."""
    stage = int(p.work.get("stage") or 1)
    missing = steps.exit_check(stage, p.work)
    fix = readiness.summary(p.work).get("fix_first") or []
    selection = " ".join(str(_screen(state).get("selection") or "").split())
    lines = ["## Right now",
             on_screen(p, state),
             "The person " + ("can change this proposal." if p.can_edit else "can only read this proposal."),
             ("To leave this step: " + "; ".join(missing) + ".") if missing else "Nothing stops this step being left.",
             *(["Still to fix before sending: " + "; ".join(fix[:6]) + "."] if fix and stage > 1 else [])]
    if rewrite := [f"{s.label} [{s.code}]" for s in sections(p.work)
                   if ((p.work.get("sections") or {}).get(s.code) or {}).get("needs_rewrite")]:
        lines.append("Marked NEEDS REWRITING, because a fact it cites was corrected or set aside: "
                     + ", ".join(rewrite) + ".")
    if others := outside(p):
        lines += ["Changed outside this chat:", *others]
    if files := reading(p.work):
        lines += ["Files read for this proposal:", *files]
    lines += ["Waiting:", *(waiting(p) or ["- nothing"])]
    if selection:
        lines.append(f"Selected text: \"{selection[:SCREEN_TEXT]}{'…' if len(selection) > SCREEN_TEXT else ''}\"")
    return "\n".join(lines)
