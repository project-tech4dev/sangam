"""Secondary research's one paragraph per topic, from the facts it found: a cheap model writes it, code traces it."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.proposals import facts as fact_rules
from app.proposals import trace

logger = logging.getLogger(__name__)

LABELS = {"problem": "The problem, measured", "place": "Why this place", "government": "What government does",
          "sdg": "SDGs", "elsewhere": "What worked elsewhere"}
SUMMARY_TEXT = 1500
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
