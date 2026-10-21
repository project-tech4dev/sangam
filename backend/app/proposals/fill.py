"""Filling the funder's form from the written parts: one model call, and code that refuses any answer adding a claim."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.proposals import assemble, trace

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "form_fill.md").read_text(encoding="utf-8")
UNITS = {"chars": "characters", "words": "words", "pages": "pages"}
How = Literal["answered", "as_written", "too_long", "no_part", "you_fill"]
_GAP = re.compile(r"\[Add:[^\]]*\]")


class Answer(BaseModel):
    code: str = Field(description="The heading's code, exactly as given.")
    text: str = Field(description="The answer, from the text given for that heading.")


class Answers(BaseModel):
    answers: list[Answer]


@dataclass(frozen=True)
class Filled:
    heading: dict[str, Any]
    text: str
    how: How
    cut: tuple[str, ...] = ()


def title(heading: dict[str, Any]) -> str:
    return f"{heading['number']}. {heading['label']}" if heading.get("number") else heading["label"]


def size(limit: dict[str, Any], text: str) -> int:
    plain = assemble.plain(text)
    return len(plain.split()) if limit["unit"] == "words" else len(plain)


def over(limit: dict[str, Any] | None, text: str) -> str | None:
    """Why the text is too long for the form; a page limit is shown, never checked."""
    if not limit or limit["unit"] == "pages" or (n := size(limit, text)) <= limit["n"]:
        return None
    return f"{n:,} {UNITS[limit['unit']]}; the form allows {limit['n']:,}"


def sources(heading: dict[str, Any], written: dict[str, str]) -> str:
    return "\n\n".join(written[c] for c in heading.get("uses") or [] if written.get(c))


def check(source: str, answer: str, limit: dict[str, Any] | None, *, districts: set[str] = frozenset(),
          names: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(why the answer is refused, the figures, places and names it cut). A cut is allowed; an addition is not. Pure."""
    was = dict(trace.extract(source, districts=districts, names=names))
    now = dict(trace.extract(answer, districts=districts, names=names))
    added = [shown for k, shown in now.items() if k not in was and not k.startswith("gap ")]
    refused = [f"added {', '.join(added)}"] if added else []
    if too := over(limit, answer):
        refused.append(too)
    return refused, [shown for k, shown in was.items() if k not in now and not k.startswith("gap ")]


async def fill(headings: list[dict[str, Any]], written: dict[str, str], style: str, model: Any) -> dict[str, str]:
    """Each prose heading's answer by code, from the parts it uses; {} when the call fails."""
    asked = [(h, s) for h in headings if h["kind"] == "prose" and (s := sources(h, written))]
    if not asked:
        return {}
    ask = f"The style:\n{style}\n\n" + "\n\n".join(
        f'<heading code="{h["code"]}" title="{title(h)}" limit="{_limit(h["limit"])}">\n'
        f"<asks>{h['ask']}</asks>\n<text>\n{s}\n</text>\n</heading>" for h, s in asked)
    try:
        out = await model.with_structured_output(Answers).ainvoke([SystemMessage(PROMPT), HumanMessage(ask)])
    except Exception:
        logger.exception("filling the funder's form failed")
        return {}
    return {a.code.strip(): a.text.strip() for a in out.answers if a.text.strip()}


def _limit(limit: dict[str, Any] | None) -> str:
    return f"{limit['n']} {UNITS[limit['unit']]}" if limit else "none"


def resolve(headings: list[dict[str, Any]], written: dict[str, str], answers: dict[str, str], *,
            earlier_phase: bool, districts: set[str] = frozenset(), names: set[str] = frozenset()) -> list[Filled]:
    """What goes under every heading: a checked answer, the parts as written, or a mark. Never blocks. Pure."""
    out: list[Filled] = []
    for h in headings:
        if h["kind"] == "skip" or (h.get("only_if") == "earlier_phase" and not earlier_phase):
            continue
        if h["kind"] != "prose":
            out.append(Filled(h, f"[You fill: {h['ask'] or h['label']}]", "you_fill"))
            continue
        source = sources(h, written)
        if not source:
            out.append(Filled(h, f"[Add: {h['ask'] or h['label']}]", "no_part"))
            continue
        if answer := answers.get(h["code"]):
            refused, cut = check(source, answer, h["limit"], districts=districts, names=names)
            if not refused:
                # An answer that is only [Add: …] marks says the parts don't answer this heading.
                gaps_only = not _GAP.sub("", answer).strip()
                out.append(Filled(h, answer, "no_part") if gaps_only else Filled(h, answer, "answered", tuple(cut)))
                continue
        if not (too := over(h["limit"], source)):
            out.append(Filled(h, source, "as_written"))
            continue
        out.append(Filled(h, f"[Add: {h['label']}: Sangam's text runs to {too}]", "too_long"))
    return out


def report(filled: list[Filled]) -> dict[str, Any]:
    """What happened under each heading, by the form's own numbering, for the screen."""
    by = {how: [title(f.heading) for f in filled if f.how == how] for how in ("answered", "as_written", "you_fill")}
    return {"answered": by["answered"], "cut": {title(f.heading): list(f.cut) for f in filled if f.cut},
            "as_written": by["as_written"], "add": [title(f.heading) for f in filled if f.how in ("too_long", "no_part")],
            "you_fill": by["you_fill"]}
