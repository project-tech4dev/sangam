"""A section's score, 0 to 2: one cheap model call says which strong elements the text covers. It never blocks a save."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.proposals import rubric, trace

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "section_grade.md").read_text(encoding="utf-8")


class Graded(BaseModel):
    covered: list[str] = Field(default_factory=list, description="Strong elements the text covers, in the rubric's words.")
    missing: list[str] = Field(default_factory=list, description="Strong elements it does not cover, in the rubric's words.")



async def grade(section: rubric.Section, text: str, model: Any) -> Graded | None:
    """None when the call fails or the section has no strong elements to grade against (a form's own question)."""
    if not section.strong:
        return None
    body = trace.GAP.sub("[gap]", trace.CITE.sub("", text))
    ask = (f"Section: {section.label}\nIt asks: {section.question}\nA strong answer holds:\n"
           + "\n".join(f"- {e}" for e in section.strong) + f"\n\nThe text:\n{body}")
    try:
        graded = await model.with_structured_output(Graded).ainvoke([SystemMessage(PROMPT), HumanMessage(ask)])
    except Exception:
        logger.exception("grading %s failed", section.code)
        return None
    known = {e.lower(): e for e in section.strong}
    missing = [known[m.lower()] for m in graded.missing if m.lower() in known]
    return Graded(covered=[e for e in section.strong if e not in missing], missing=missing)
