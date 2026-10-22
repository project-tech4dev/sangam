"""Filling the funder's form: one model call over all the written parts, and code that refuses any answer adding a claim."""

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
How = Literal["answered", "add", "you_fill"]
_GAP = re.compile(r"\[Add:[^\]]*\]")
_CUT = re.compile(r"[.!?\];](?=\s)")  # where a cut leaves whole clauses
_YOU = re.compile(r"\[You fill:[^\]]*\]")


class Answer(BaseModel):
    code: str = Field(description="The heading's code, exactly as given.")
    text: str = Field(description="The answer, from the text given.")


class Answers(BaseModel):
    answers: list[Answer]


@dataclass(frozen=True)
class Filled:
    heading: dict[str, Any]
    text: str
    how: How


def title(heading: dict[str, Any]) -> str:
    return f"{heading['number']}. {heading['label']}" if heading.get("number") else heading["label"]


def shown(heading: dict[str, Any]) -> str:
    """The heading as the file shows it: with the form's limit, so the person sees it while editing."""
    limit = heading.get("limit")
    return f"{title(heading)} (max {limit['n']:,} {UNITS[limit['unit']]})" if limit else title(heading)


def outline(filled: list[Filled]) -> list[tuple[str, str, int]]:
    """(heading, text, level) for the Word file: a group's title once, over the fields in it."""
    out: list[tuple[str, str, int]] = []
    last = None
    for f in filled:
        group = f.heading.get("group")
        if group and group != last:
            out.append((group, "", 1))
        last = group
        out.append((shown(f.heading), f.text, 2 if group else 1))
    return out


def size(limit: dict[str, Any], text: str) -> int:
    plain = assemble.plain(text)
    return len(plain.split()) if limit["unit"] == "words" else len(plain)


def over(limit: dict[str, Any] | None, text: str) -> str | None:
    """Why the text is too long for the form; a page limit is shown, never checked."""
    if not limit or limit["unit"] == "pages" or (n := size(limit, text)) <= limit["n"]:
        return None
    return f"{n:,} {UNITS[limit['unit']]}; the form allows {limit['n']:,}"


def everything(written: dict[str, str], about: str = "") -> str:
    """All the written parts, each led by its code, plus what Sangam knows of the org: what every answer comes from."""
    parts = "\n\n".join(f"[{code}]\n{text}" for code, text in written.items() if text)
    return f"{about}\n\n{parts}".strip()


def check(source: str, answer: str, limit: dict[str, Any] | None, *, districts: set[str] = frozenset(),
          names: set[str] = frozenset()) -> list[str]:
    """Why the answer is refused: a figure, place or name the text lacks, or the form's limit. Pure."""
    was = dict(trace.extract(source, districts=districts, names=names))
    now = dict(trace.extract(answer, districts=districts, names=names))
    added = [shown for k, shown in now.items() if k not in was and not k.startswith("gap ")]
    refused = [f"added {', '.join(added)}"] if added else []
    if too := over(limit, answer):
        refused.append(f"ran to {too}")
    return refused


def fit(answer: str, limit: dict[str, Any]) -> str | None:
    """The answer cut to the limit at the last sentence end or ";" that fits; never at a comma, which splits a list. Pure."""
    answer = answer.strip()
    for end in reversed([m.end() for m in _CUT.finditer(answer)]):
        text = answer[:end].rstrip(";").rstrip() + ("." if answer[end - 1] == ";" else "")
        if not over(limit, text):
            return text
    return None


def asked(heading: dict[str, Any]) -> bool:
    return heading["kind"] in ("prose", "field")


async def fill(headings: list[dict[str, Any]], written: dict[str, str], style: str, model: Any,
               about: str = "") -> dict[str, str]:
    """Every prose and field heading's answer by code, in one call over all the parts; {} when the call fails."""
    text = everything(written, about)
    todo = [h for h in headings if asked(h)]
    if not text or not todo:
        return {}
    ask = (f"The style:\n{style}\n\n<text>\n{text}\n</text>\n\n" + "\n".join(
        f'<heading code="{h["code"]}" kind="{h["kind"]}" title="{title(h)}" limit="{_limit(h["limit"])}">'
        f'{h["ask"]}</heading>' for h in todo))
    try:
        out = await model.with_structured_output(Answers).ainvoke([SystemMessage(PROMPT), HumanMessage(ask)])
    except Exception:
        logger.exception("filling the funder's form failed")
        return {}
    return {a.code.strip(): a.text.strip() for a in out.answers if a.text.strip()}


def _limit(limit: dict[str, Any] | None) -> str:
    return f"{limit['n']} {UNITS[limit['unit']]}" if limit else "none"


def _mark(h: dict[str, Any]) -> Filled:
    asks = h["ask"] or h["label"]
    if h["kind"] != "prose":
        return Filled(h, f"[You fill: {asks}]", "you_fill")
    limit = f" (the form allows {_limit(h['limit'])})" if h["limit"] else ""
    return Filled(h, f"[Add: {asks}{limit}]", "add")


def resolve(headings: list[dict[str, Any]], written: dict[str, str], answers: dict[str, str], *,
            earlier_phase: bool, about: str = "", districts: set[str] = frozenset(),
            names: set[str] = frozenset()) -> list[Filled]:
    """What goes under every heading: a checked answer or a mark. Never blocks. Pure."""
    source = everything(written, about)
    out: list[Filled] = []
    for h in headings:
        if h["kind"] == "skip" or (h.get("only_if") == "earlier_phase" and not earlier_phase):
            continue
        answer = answers.get(h["code"]) if asked(h) else None
        if not answer:
            out.append(_mark(h))
            continue
        if over(h["limit"], answer) and not check(source, answer, None, districts=districts, names=names):
            answer = fit(answer, h["limit"]) or answer
        if refused := check(source, answer, h["limit"], districts=districts, names=names):
            logger.info("form heading %s refused: %s", title(h), "; ".join(refused))
            out.append(_mark(h))
            continue
        # An answer that is only marks says the text doesn't answer this heading.
        empty = not re.sub(r"[\W_]+", "", _GAP.sub("", _YOU.sub("", answer)))
        if empty and h["kind"] != "prose":
            out.append(_mark(h))
        else:
            out.append(Filled(h, answer, "add" if empty else "answered"))
    return out


def report(filled: list[Filled]) -> dict[str, Any]:
    """What happened under each heading, by the form's own numbering, for the screen."""
    return {how: [title(f.heading) for f in filled if f.how == how] for how in ("answered", "add", "you_fill")}
