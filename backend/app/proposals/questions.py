"""When Sangam Pitch may ask, decided by code from the fact list. `may_ask` is the one gate; `warranted` the reasons.

A question lives in `work.questions` with who it was asked of, because each person's chat is private and the
answer belongs to the shared proposal.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.proposals import facts as fact_rules
from app.proposals import reliability

logger = logging.getLogger(__name__)

REASONS = ("missing", "disagree", "org_call")
STATUSES = ("open", "parked", "answered", "closed")
ORG_CALL_KINDS = ("programme", "amount", "gate")
LATER = ("later", "skip", "not now", "ask me later", "skip for now", "i don't know", "don't know", "dont know")


def gap(q: dict[str, Any]) -> str:
    """What a question is about: a section's element when one is missing, else its subject."""
    about = q.get("element") if q.get("reason") == "missing" else q.get("subject")
    return f"{q.get('section')}|{fact_rules.norm(about)}"


def filled(work: dict[str, Any], q: dict[str, Any]) -> str | None:
    """The live fact that now answers this gap, if any."""
    for k, f in (work.get("facts") or {}).items():
        if not fact_rules.is_live(f) or f.get("section") != q.get("section"):
            continue
        if q.get("reason") == "missing":
            if f.get("element") and fact_rules.norm(f["element"]) == fact_rules.norm(q.get("element")):
                return k
        elif fact_rules.norm(f.get("subject")) == fact_rules.norm(q.get("subject")) and f.get("origin") == "you_said":
            return k
    return None


def warranted(work: dict[str, Any], q: dict[str, Any]) -> str | None:
    """Why this question is not warranted by the fact list, or None when it is."""
    section = fact_rules.section_of(work, q.get("section"))
    if section is None:
        return f"no section {q.get('section')!r} in this proposal"
    reason = q.get("reason")
    if reason not in REASONS:
        return f"a reason to ask is one of {', '.join(REASONS)}"
    if reason == "missing":
        if fact_rules.element_of(section, q.get("element")) is None:
            return f"{section.label} needs: {'; '.join(section.strong)}. Name one of those as the element."
    elif reason == "disagree":
        held = work.get("facts") or {}
        pair = [held.get(k) for k in q.get("facts") or []]
        if len(pair) != 2 or None in pair:
            return "a disagreement names the two facts that disagree"
        a, b = pair
        if not (fact_rules.is_live(a) and fact_rules.is_live(b)):
            return "one of those facts is no longer in use"
        if (a.get("kind"), fact_rules.norm(a.get("subject")), a.get("as_of")) != \
                (b.get("kind"), fact_rules.norm(b.get("subject")), b.get("as_of")):
            return "those facts are not about the same thing for the same period"
        if reliability.rank(a.get("tier", "")) != reliability.rank(b.get("tier", "")):
            return "the stronger source wins; use it and say so"
        if fact_rules.norm(a.get("value")) == fact_rules.norm(b.get("value")):
            return "those facts agree"
    elif reason == "org_call" and q.get("kind") not in ORG_CALL_KINDS:
        return f"only the organisation decides its {', '.join(ORG_CALL_KINDS)}; other gaps are asked as missing"
    if k := filled(work, q):
        return f"already answered by {k}"
    return None


def may_ask(work: dict[str, Any], q: dict[str, Any], *, me: str, on_screen: str | None) -> tuple[str | None, str | None]:
    """(why not, the id of this same question already held). One open question per person; one person per gap."""
    stage = int(work.get("stage") or 1)
    if stage < 3:
        return "questions start at step 3, when the proposal is being written", None
    if stage in (3, 4) and q.get("section") != on_screen:
        return "ask only about the part the person has open on screen", None
    held = work.get("questions") or {}
    same = next((k for k, x in held.items() if gap(x) == gap(q) and x.get("status") in ("open", "parked")), None)
    for k, x in held.items():
        if x.get("status") != "open" or k == same:
            continue
        if str((x.get("asked_of") or {}).get("id")) == me:
            return f"this person already has a question open about {x.get('subject')}; wait for it", None
    if same and held[same].get("status") == "open" and str((held[same].get("asked_of") or {}).get("id")) != me:
        who = (held[same].get("asked_of") or {}).get("name") or "a teammate"
        return f"{who} was asked this and has not answered yet; ask about something else", None
    return warranted(work, q), same


def next_id(work: dict[str, Any]) -> str:
    taken = [int(k[1:]) for k in (work.get("questions") or {}) if k[1:].isdigit()]
    return f"q{max(taken, default=0) + 1}"


class _Kind(BaseModel):
    kind: Literal["answer", "question", "skip"]


PROMPT = """Sangam asked a person a question while writing their grant proposal. Sort their reply:
- answer: it answers the question, even partly or with "no, we don't have that".
- question: it asks something back or asks what the question means, without answering.
- skip: it puts the question off ("later", "not now", "I'll check").
Reply with the kind only."""


async def classify(text: str, question: str, model: Any) -> str:
    """answer, question or skip. A failed call is a question back: nothing is written from a reply not understood."""
    if fact_rules.norm(text).strip(" .!") in LATER:
        return "skip"
    try:
        reply = await model.with_structured_output(_Kind).ainvoke(
            [SystemMessage(PROMPT), HumanMessage(f"Question: {question}\n\nReply: {text}")])
        return reply.kind
    except Exception:
        logger.exception("sorting a reply failed")
        return "question"
