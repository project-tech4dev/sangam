"""The fact list and the one question at a time: Sangam Pitch proposes, code checks the source and the reason."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.agent.models import resolve_model
from app.core.config import get_settings
from app.db.pool import get_pool
from app.ingest import run_sources
from app.proposals import context, records, steps
from app.proposals import facts as fact_rules
from app.proposals import questions as question_rules
from app.proposals import work as work_rules
from app.proposals.middleware import PUBLIC_RUN, page_key
from app.proposals.tools.proposal_tools import NO_PROPOSAL, require_edit
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

QUESTION = "proposal_question"  # the interrupt's type; QuestionCard.tsx shows only this one
_CODE = re.compile(r"\s*\[(?:org|funder|activity|grant|score|news|graph|vault):[^\]]*\]|\s*⟦k\d+⟧")


def _words(text: str) -> str:
    """The card is on screen, where no marker is shown, whatever the model wrote."""
    return _CODE.sub("", text or "").strip()


class FactIn(BaseModel):
    subject: str = Field(description="What the fact is about, in words: 'households surveyed in Udalguri'.")
    value: str = Field(description="The value exactly as the source gives it: '1,240', '₹2.40 crore', '96 villages'.")
    origin: str = Field(description="registry, vault, web or derived.")
    kind: str = Field("", description="figure, place, programme, amount, date, name or gate.")
    section: str = Field("", description="The section code this fact serves, for example A3.")
    element: str = Field("", description="Which of that section's strong elements it fills, in the section's words.")
    as_of: str = Field("", description="The year or period the value is for: '2024-25'.")
    marker: str = Field("", description="registry: the [org:N], [activity:N] or [score:N] the value came with.")
    evidence: str = Field("", description="vault: the quoted text with its [vault:N#…] marker; web: the quoted text.")
    source_url: str = Field("", description="vault or web: the URL the value came from.")
    source_name: str = Field("", description="The source in words: 'Annual report 2024-25'.")
    topic: str = Field("", description="public research only: problem, place, government, sdg or elsewhere.")
    page: int | None = Field(None, description="vault: the page.")
    document_id: int | None = Field(None, description="vault: the file's document id.")
    derived_from: list[str] = Field(default_factory=list, description="derived: the fact ids it is worked out from.")


def _clean(f: FactIn) -> dict[str, Any]:
    out = f.model_dump(exclude={"derived_from"})
    out["from"] = f.derived_from
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in out.items()}


class _Refused(Exception):
    pass


@tool
async def add_facts(facts: list[FactIn]) -> str:
    """Add facts to the proposal's fact list. Code checks each one's source before it is kept.

    - registry: the value must appear in the row its marker names ([org:N], [activity:N], [score:N]), as
      read_org_record or read_match gave it.
    - vault: the file must be one ticked for this proposal, with its [vault:N#…] marker in the evidence.
    - web: an http link and at least 20 characters quoted from the page.
    - derived: names the facts it is worked out from; it stays unchecked until the person confirms it.
    What the person tells you is never added here: ask_user stores their answer.

    Give each fact the section it serves and, when it fills one, the element of that section's strong answer.
    Adding the same fact twice returns the id it already has. Facts arrive "proposed": the person confirms them on
    screen.

    Args:
        facts: the facts to add.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if refused := require_edit(p):
            return refused
        if early := steps.too_early("add_facts", int(p.work.get("stage") or 1)):
            return f"REFUSED: {early}."
        pool = get_pool()
        out: list[str] = []
        keep: list[dict[str, Any]] = []
        for raw in facts:
            fact = _clean(raw)
            why = fact_rules.problem(p.work, fact)
            if why is None and fact["origin"] == "registry":
                why = await records.check(pool, p, fact)
            # A reader cites only the file it was given; the funder's reader, none of the org's.
            reading = run_sources.CURRENT.get()
            if why is None and fact["origin"] == "vault" and reading and fact.get("document_id") not in reading.vault_docs:
                why = f"{fact['subject']}: this reader may cite only the file it was given"
            if (public := PUBLIC_RUN.get()) is not None:
                why = why or fact_rules.off_page(fact, public.pages.get(page_key(fact.get("source_url"))))
                fact["found_by"] = "public"
                if public.ask:
                    fact["ask"] = public.ask
            if why:
                out.append(f"REFUSED {why}")
                continue
            if fact.get("element"):
                fact["element"] = fact_rules.element_of(fact_rules.section_of(p.work, fact["section"]), fact["element"])
            keep.append(fact_rules.make(fact))
        if not keep:
            return "\n".join(out) or "No facts given."

        by = await repo.user_name(pool, p.scope.user_id)
        added: list[tuple[str, dict[str, Any], bool]] = []

        def change(work: dict, title: str) -> work_rules.Applied | None:
            held = {"facts": dict(work.get("facts") or {})}
            changes: dict[str, Any] = {}
            for fact in keep:
                if k := fact_rules.same_as(held, fact):
                    added.append((k, fact, False))
                    continue
                k = fact_rules.next_id(held)
                held["facts"][k] = changes[f"facts.{k}"] = fact
                added.append((k, fact, True))
            if not changes:
                raise _Refused
            return work_rules.apply(work, changes, by=by, via="agent", reason="checked against its source",
                                    facts=list(changes), title=title)

        try:
            if await repo.save(pool, p.id, change) is None:
                return NO_PROPOSAL
        except _Refused:
            pass
        out += [f"{k} {'added' if new else 'already held'}: {f['subject']} = {f['value']} ({f['tier']})"
                for k, f, new in added]
        return "\n".join(out)
    except Exception as exc:
        logger.exception("add_facts failed")
        return f"add_facts failed: {type(exc).__name__}"


@tool
async def ask_user(reason: str, section: str, subject: str, found: str, missing: str, why: str,
                   runtime: ToolRuntime, suggestion: str = "", element: str = "", kind: str = "",
                   facts: list[str] | None = None, options: list[str] | None = None) -> str:
    """Ask the person one question, on a card above their chat, and wait for the reply. Code checks first.

    Ask only when the fact list warrants it, about the part they have open on screen, one question at a time:
    - reason "missing": a strong element of the section has no fact. Name it as `element`, in the section's words.
    - reason "disagree": two facts about the same thing and period, from equally strong sources, differ. Give both
      ids as `facts`.
    - reason "org_call": only the organisation can decide it: `kind` is programme, amount or gate.
    A question already asked of a teammate and still open is refused: ask about something else.

    Write it in four short parts, in plain words with no codes: what you found, what is missing, why the funder
    cares, and a suggestion when you have one. `options` puts up to four answers on the card as buttons.

    It returns ANSWERED (the reply is now a fact the person said), QUESTION BACK (answer their question, then call
    ask_user again with the same question), or PARKED (they will answer later; go on with something else).

    Args:
        reason: missing, disagree or org_call.
        section: the code of the part on screen, for example A3.
        subject: what the question is about, in words: "causes of the food gap".
        found: what Sangam already holds on it, in words.
        missing: what is not known.
        why: why the funder cares.
        suggestion: where the answer might be, or a likely answer.
        element: for missing, the strong element with no fact.
        kind: for org_call, programme, amount or gate.
        facts: for disagree, the two fact ids.
        options: up to four short answers to offer as buttons.
    """
    try:
        p = await context.current()
        if p is None:
            return NO_PROPOSAL
        if refused := require_edit(p):
            return refused
        me = str(p.scope.user_id)
        q: dict[str, Any] = {"reason": reason, "section": section.strip(), "subject": subject.strip(),
                             "kind": kind.strip() or None, "facts": facts or []}
        if reason == "missing" and (s := fact_rules.section_of(p.work, q["section"])):
            q["element"] = fact_rules.element_of(s, element) or element
        on_screen = context.screen_part(p.work, runtime.state)
        why_not, same = question_rules.may_ask(p.work, q, me=me, on_screen=on_screen)
        pool = get_pool()
        by = await repo.user_name(pool, p.scope.user_id)
        if why_not:
            held = (p.work.get("questions") or {}).get(same or "") or {}
            if same and held.get("status") == "parked" and why_not.startswith("already answered"):
                await _set_question(pool, p.id, same, {**held, "status": "closed"}, by, "a fact now answers it")
            return f"REFUSED: {why_not}."

        label = fact_rules.section_of(p.work, q["section"]).label
        card = {"found": _words(found), "missing": _words(missing), "why": _words(why),
                "suggestion": _words(suggestion), "options": [_words(o) for o in (options or []) if o.strip()][:4]}
        try:
            qid = await _open(pool, p.id, q, card, by, me, on_screen)
        except _Refused as raced:  # a teammate's question landed between the check and the lock
            return f"REFUSED: {raced}."
        # `ask` is this call's id: a question asked again after a question back is a new card on screen.
        reply = interrupt({"type": QUESTION, "id": qid, "ask": runtime.tool_call_id, "part": label,
                           "subject": q["subject"], **card})

        kind_of, text = _reply(reply)
        if kind_of == "text":
            kind_of = await question_rules.classify(
                text, f"{found} {missing}", resolve_model(get_settings().utility_model))
        if kind_of == "skip":
            await _set_question(pool, p.id, qid, None, by, "the person will answer later", status="parked")
            return f"PARKED: {by['name']} will answer about {q['subject']} later. Go on with something else."
        if kind_of == "question":
            return (f"QUESTION BACK: the person asked: {text!r}. Answer it from what you hold, then call ask_user "
                    "again with the same question so its card shows again.")
        k = await _answer(pool, p.id, qid, text, by)
        return f"ANSWERED: {by['name']} said {text!r} about {q['subject']}. Stored as {k}, a fact they said."
    except GraphBubbleUp:
        raise  # the pause itself: the run waits here for the person's reply
    except Exception as exc:
        logger.exception("ask_user failed")
        return f"ask_user failed: {type(exc).__name__}"


def _reply(reply: Any) -> tuple[str, str]:
    """A card button is {kind: pick, choice}; the chat box is {kind: text, text}."""
    reply = reply if isinstance(reply, dict) else {"kind": "text", "text": str(reply or "")}
    if reply.get("kind") == "pick":
        choice = str(reply.get("choice") or "").strip()
        return ("skip", choice) if choice.lower() == "later" else ("answer", choice)
    return "text", str(reply.get("text") or "").strip()


async def _open(pool: Any, proposal_id: int, q: dict[str, Any], card: dict[str, Any], by: dict[str, Any],
                me: str, on_screen: str | None) -> str:
    """Record the question as open, asked of this person; a resumed run finds it already open and writes nothing."""
    qid: list[str] = []

    def change(work: dict, title: str) -> work_rules.Applied:
        why_not, same = question_rules.may_ask(work, q, me=me, on_screen=on_screen)
        if why_not:
            raise _Refused(why_not)
        held = (work.get("questions") or {}).get(same or "") or {}
        qid.append(same or question_rules.next_id(work))
        if held.get("status") == "open":
            raise _AlreadyOpen
        question = {**q, **card, "status": "open", "asked_of": by, "asked_at": datetime.now(UTC).isoformat()}
        return work_rules.apply(work, {f"questions.{qid[0]}": question}, by=by, via="agent",
                                reason=f"asked about {q['subject']}", title=title)

    try:
        await repo.save(pool, proposal_id, change)
    except _AlreadyOpen:
        pass
    return qid[0]


async def _set_question(pool: Any, proposal_id: int, qid: str, question: dict[str, Any] | None, by: dict[str, Any],
                        reason: str, status: str | None = None) -> None:
    def change(work: dict, title: str) -> work_rules.Applied:
        held = (work.get("questions") or {}).get(qid) or {}
        value = question or {**held, "status": status, "asked_of": None}
        return work_rules.apply(work, {f"questions.{qid}": value}, by=by, via="agent", reason=reason, title=title)

    await repo.save(pool, proposal_id, change)


async def _answer(pool: Any, proposal_id: int, qid: str, text: str, by: dict[str, Any]) -> str:
    """The reply becomes a fact the person said, and the question is answered, in one save."""
    out: list[str] = []

    def change(work: dict, title: str) -> work_rules.Applied:
        question = (work.get("questions") or {}).get(qid) or {}
        fact = fact_rules.said(question, text, by)
        k = fact_rules.same_as(work, fact) or fact_rules.next_id(work)
        out.append(k)
        changes: dict[str, Any] = {f"questions.{qid}": {**question, "status": "answered", "answer": k}}
        if k not in (work.get("facts") or {}):
            changes[f"facts.{k}"] = fact
        return work_rules.apply(work, changes, by=by, via="agent", reason="the person answered", facts=[k], title=title)

    await repo.save(pool, proposal_id, change)
    return out[0]


class _AlreadyOpen(Exception):
    pass
