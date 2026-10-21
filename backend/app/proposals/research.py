"""Secondary research's one paragraph per topic, from the facts it found: a cheap model writes it, code traces it."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.proposals import facts as fact_rules
from app.proposals import rubric, trace

logger = logging.getLogger(__name__)

LABELS = {"problem": "The problem, measured", "place": "Why this place", "government": "What government does",
          "sdg": "SDGs", "elsewhere": "What worked elsewhere"}
SUMMARY_TEXT = 1500
ASK_KINDS = ("deeper", "chat", "plan")  # step 3's "Research deeper", a chat request, step 4's research card
ASK_TEXT = 500
FOCUS_ITEMS, FOCUS_TEXT, SITES = 8, 120, 5
FOUND_LISTED = 40  # subjects already found, so a deeper run looks past them
_HOST = re.compile(r"^(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/?#].*)?$")
_BY_SECTION = {"A3": "problem", "A2": "place", "A4": "elsewhere", "A14": "government"}

PROMPT = """You summarise public research for an Indian NGO writing a grant proposal. You get one topic and the facts
found on it, each with its id. Write one short paragraph, two to four sentences, saying what the facts show together.
- Use only the facts given. Copy each figure exactly as its fact gives it, with its place and year.
- Put the fact's id as ⟦k7⟧ right after each claim it holds. Every sentence cites at least one fact.
- No figure, place, scheme or name that is not in a cited fact. No advice, no opinion, no mention of the NGO."""


class _Paragraph(BaseModel):
    text: str = Field(description="One paragraph citing each fact as ⟦kN⟧ right after the claim it holds.")


def topic_of(fact: dict[str, Any]) -> str:
    """A fact saved before facts carried a topic falls back to its section, as the screen does."""
    if fact.get("topic") in LABELS:
        return fact["topic"]
    if fact.get("section") == "F1":
        return "sdg" if str(fact.get("subject") or "").strip().upper().startswith("SDG") else "government"
    return _BY_SECTION.get(fact.get("section") or "", "problem")


def found(work: dict[str, Any], topic: str) -> dict[str, dict[str, Any]]:
    """The topic's facts still in use, from secondary research only."""
    return {k: f for k, f in (work.get("facts") or {}).items()
            if f.get("found_by") == "public" and fact_rules.is_live(f) and topic_of(f) == topic}


def _ask(topic: str, facts: dict[str, dict[str, Any]]) -> str:
    lines = [f"- {k} · {f.get('subject')}: {f.get('value')}" + (f" ({f['as_of']})" if f.get("as_of") else "")
             + (f" · {f['source_name']}" if f.get("source_name") else "") for k, f in facts.items()]
    return f"Topic: {LABELS[topic]}\n\nFacts:\n" + "\n".join(lines)


def checked(text: str, facts: dict[str, dict[str, Any]]) -> str | None:
    """The paragraph when every id it cites is the topic's and every claim traces to one; else None."""
    text = " ".join((text or "").split())
    ids = trace.cited(text)
    if not text or len(text) > SUMMARY_TEXT or not ids or any(k not in facts for k in ids):
        return None
    return None if trace.unsourced(text, facts) else text


async def _one(topic: str, facts: dict[str, dict[str, Any]], model: Any) -> str | None:
    try:
        reply = await model.with_structured_output(_Paragraph).ainvoke(
            [SystemMessage(PROMPT), HumanMessage(_ask(topic, facts))])
    except Exception:
        logger.exception("summarising %s failed", topic)
        return None
    text = checked(reply.text, facts)
    if text is None:
        logger.warning("summary of %s refused: a claim did not trace to its facts", topic)
    return text


async def summarise(work: dict[str, Any], model: Any) -> dict[str, str]:
    """{topic: paragraph} for each topic with facts; a topic whose paragraph failed the check is left out."""
    topics = [t for t in LABELS if found(work, t)]
    texts = await asyncio.gather(*(_one(t, found(work, t), model) for t in topics))
    return {t: text for t, text in zip(topics, texts, strict=True) if text}


def bad_ask(ask: Any) -> str | None:
    """Why a stored research ask is malformed, or None."""
    if not isinstance(ask, dict) or ask.get("kind") not in ASK_KINDS or not ask.get("at"):
        return f"a research ask has a kind ({', '.join(ASK_KINDS)}) and a time"
    if ask.get("status") not in ("running", "done", "failed"):
        return "a research ask is running, done or failed"
    if len(str(ask.get("ask") or "")) > ASK_TEXT:
        return f"a research ask is up to {ASK_TEXT} characters"
    lists = (ask.get("focus") or [], ask.get("sites") or [], ask.get("sections") or [])
    if any(not isinstance(v, list) or len(v) > FOCUS_ITEMS or not all(isinstance(x, str) for x in v) for v in lists):
        return f"a research ask's focus, sites and sections are lists of up to {FOCUS_ITEMS}"
    return None


def next_ask_id(work: dict[str, Any]) -> str:
    taken = [int(k[1:]) for k in (work.get("research_asks") or {}) if k[1:].isdigit()]
    return f"a{max(taken, default=0) + 1}"


def focus(items: list[str], avoid: set[str]) -> tuple[list[str], list[str]]:
    """The angles that may go into a search, and those dropped for naming the org, a partner or a person."""
    kept, dropped = [], []
    for item in items:
        text = " ".join(str(item or "").split())[:FOCUS_TEXT]
        if not text:
            continue
        named = any(n and re.search(rf"\b{re.escape(n)}\b", fact_rules.norm(text)) for n in avoid)
        (dropped if named else kept).append(text)
    return kept[:FOCUS_ITEMS], dropped


def sites(items: list[str]) -> list[str]:
    """Each site as its host, so the task can say site:<host>; anything not a web address is dropped."""
    hosts = [m.group(1) for m in (_HOST.match(str(i or "").strip().lower()) for i in items) if m]
    return list(dict.fromkeys(hosts))[:SITES]


def already_found(work: dict[str, Any]) -> list[str]:
    """What public research has found and still uses; public already, so a deeper run may be told."""
    return [f"{f.get('subject')}: {f.get('value')}" for f in (work.get("facts") or {}).values()
            if f.get("found_by") == "public" and fact_rules.is_live(f)][:FOUND_LISTED]


def reset(work: dict[str, Any]) -> dict[str, Any]:
    """Deleting secondary research: its run and asks, and every public fact no part's text cites, another fact
    derives from, or a correction replaced. They go, not just set aside, so a fresh search can find them again."""
    facts = work.get("facts") or {}
    texts = " ".join((s or {}).get("text") or "" for s in (work.get("sections") or {}).values())
    kept = (set(trace.cited(texts)) | {k for f in facts.values() for k in (f.get("from") or [])}
            | {f["supersedes"] for f in facts.values() if f.get("supersedes")})
    changes: dict[str, Any] = {f"facts.{k}": None for k, f in facts.items()
                               if f.get("found_by") == "public" and k not in kept}
    if (work.get("readers") or {}).get("public") is not None:
        changes["readers.public"] = None
    if work.get("research_asks"):
        changes["research_asks"] = None
    return changes


DEEPER_FROM = ("A1", "A2", "A3")  # the case: what "Research deeper" reads
DEEPER_NEEDS = ("A2", "A3")  # marked done first; the Summary waits for the plan, so it is read but not needed
_CITE = re.compile(r"\s*⟦k\d+⟧")

ANGLES_PROMPT = """You turn the case an Indian NGO wrote for a grant proposal into search angles for public research:
government data, research and evaluations on the problem and the place. Give up to eight angles, each a few words
naming one indicator, group of people, scheme or comparison with its place: "MGNREGA days worked, Udalguri",
"women's SHG credit linkage, Assam", "secondary dropout, Assam vs India".
- Every [Add: ...] gap the text leaves is an angle first: it is what the proposal still has no evidence for.
- Then what the text claims without a public figure beside it, at the district, state or national level.
- Never the organisation, a partner, a person or a village name; never advice or a question."""


class _Angles(BaseModel):
    angles: list[str] = Field(description="Up to eight search angles, a few words each, with their place.")


def not_ready(work: dict[str, Any]) -> list[str]:
    """The case's parts still to mark done before research can go deeper from them."""
    held = work.get("sections") or {}
    labels = {s.code: s.label for s in rubric.CORE}
    return [f"mark {labels[c]} done" for c in DEEPER_NEEDS if not (held.get(c) or {}).get("done")]


def case_text(work: dict[str, Any]) -> str:
    """The case's written parts, citations taken out: the angles come from what it says, not its fact ids."""
    held = work.get("sections") or {}
    labels = {s.code: s.label for s in rubric.CORE}
    parts = [(labels[c], _CITE.sub("", (held.get(c) or {}).get("text") or "").strip()) for c in DEEPER_FROM]
    return "\n\n".join(f"## {label}\n{text}" for label, text in parts if text)


async def angles(work: dict[str, Any], model: Any, avoid: set[str]) -> tuple[list[str], list[str]]:
    """Search angles from the case, those naming the org, a partner or a person dropped. Raises on a model failure."""
    reply = await model.with_structured_output(_Angles).ainvoke(
        [SystemMessage(ANGLES_PROMPT), HumanMessage(case_text(work))])
    return focus(reply.angles, avoid)
