"""Smoothing the language: one model call rewrites the parts, and code refuses it if any figure, place, name or gap moved."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.proposals import rubric, trace

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "polish.md").read_text(encoding="utf-8")


class Part(BaseModel):
    code: str = Field(description="The part's code, exactly as given.")
    text: str = Field(description="The part, smoothed.")


class Smoothed(BaseModel):
    parts: list[Part]


async def smooth(written: list[tuple[rubric.Section, str]], style: str, model: Any) -> dict[str, str] | None:
    """Each part's smoothed text by code; None when the call fails."""
    ask = f"The style:\n{style}\n\n" + "\n\n".join(
        f'<part code="{s.code}" title="{s.label}">\n{text}\n</part>' for s, text in written)
    try:
        out = await model.with_structured_output(Smoothed).ainvoke([SystemMessage(PROMPT), HumanMessage(ask)])
    except Exception:
        logger.exception("smoothing the language failed")
        return None
    return {p.code.strip(): p.text.strip() for p in out.parts if p.text.strip()}


def differences(written: list[tuple[rubric.Section, str]], smoothed: dict[str, str], *,
                districts: set[str] = frozenset(), names: set[str] = frozenset()) -> list[str]:
    """What the smoothing changed that it may not, part by part; empty means every claim survived as it was."""
    out: list[str] = []
    for section, before in written:
        after = smoothed.get(section.code)
        if after is None:
            out.append(f"{section.label}: left out")
            continue
        was = trace.extract(before, districts=districts, names=names)
        now = trace.extract(after, districts=districts, names=names)
        # Which claims, not how often: "the same 2026 survey" may become "that survey" once 2026 is said.
        lost = [shown for k, shown in dict(was).items() if k not in dict(now)]
        new = [shown for k, shown in dict(now).items() if k not in dict(was)]
        if len(lost) == 1 and len(new) == 1:
            out.append(f"{section.label}: {lost[0]} became {new[0]}")
            continue
        if lost:
            out.append(f"{section.label}: dropped {', '.join(lost)}")
        if new:
            out.append(f"{section.label}: added {', '.join(new)}")
    return out
