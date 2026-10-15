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
    states = [f"{s.label} [{s.code}]: " + ("finished" if (saved.get(s.code) or {}).get("done")
                                          else "draft" if (saved.get(s.code) or {}).get("text") else "empty")
              for s in sections(p.work)]
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


def _what(work: dict[str, Any], path: str) -> str:
    head, _, rest = path.partition(".")
    if head == "sections":
        code, _, field = rest.partition(".")
        label = next((s.label for s in sections(work) if s.code == code), code)
        return f"{label} [{code}]" + (" (marked finished or not)" if field == "done" else "")
    if head == "gates":
        return next((r["label"] for r in work.get("requirements") or [] if r["key"] == rest), "a requirement")
    if head == "facts":
        return f"fact {rest.partition('.')[0]}"
    return {"stage": "the step", "template": "the form", "skipped_template": "the form", "sources": "the files to read",
            "style": "the writing style", "title": "the title"}.get(head, head)


def by_others(p: Current) -> list[str]:
    """Teammates' latest changes, newest first: each person's chat is private, so this is how the agent hears of them."""
    me = str(p.scope.user_id) if p.scope.user_id else None
    theirs = [e for e in reversed(p.work.get("log") or []) if str((e.get("by") or {}).get("id")) != me]
    return [f"- {(e.get('by') or {}).get('name') or 'Someone'} changed {_what(p.work, e['path'])}, "
            f"{str(e.get('at', ''))[:16].replace('T', ' ')} UTC" for e in theirs[:OTHERS_SHOWN]]


def live(p: Current, state: Any) -> str:
    """The part that changes every turn: what is missing, who is asking, and where they are on screen. Never saved."""
    stage = int(p.work.get("stage") or 1)
    missing = steps.exit_check(stage, p.work)
    fix = readiness.summary(p.work).get("fix_first") or []
    screen = _screen(state)
    selection = " ".join(str(screen.get("selection") or "").split())
    lines = ["## Right now",
             "The person " + ("can change this proposal." if p.can_edit else "can only read this proposal."),
             ("To leave this step: " + "; ".join(missing) + ".") if missing else "Nothing stops this step being left.",
             *(["Still to fix before sending: " + "; ".join(fix[:6]) + "."] if fix and stage > 1 else [])]
    if others := by_others(p):
        lines += ["Changed by teammates (not in this chat):", *others]
    where = [f"{k} {screen[k]}" for k in ("step", "tab", "part") if screen.get(k)]
    if where:
        lines.append("On screen: " + ", ".join(where) + ".")
    if selection:
        lines.append(f"Selected text: \"{selection[:SCREEN_TEXT]}{'…' if len(selection) > SCREEN_TEXT else ''}\"")
    return "\n".join(lines)
