"""One Haiku call per page: the open calls it lists, in a fixed shape."""

from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.ingest.news.classify import _day
from app.ingest.taxonomy import DOMAINS, VOCABULARY

PROMPT_VERSION = "calls-v1"
MAX_PAGE_CHARS = 30_000


def _known(allowed):
    return lambda v: [x for x in (v or []) if x in allowed]


class Call(BaseModel):
    title: str
    deadline: date | None = None
    url: str | None = None
    amount_min: float | None = Field(default=None, ge=0)
    amount_max: float | None = Field(default=None, ge=0)
    states: list[str] = []
    domains: list[str] = []
    themes: list[str] = []
    eligibility: list[str] = []

    _date = field_validator("deadline", mode="before")(_day)
    _domains = field_validator("domains", mode="before")(_known(DOMAINS))
    _themes = field_validator("themes", mode="before")(_known(VOCABULARY["themes"]))


class Calls(BaseModel):
    calls: list[Call] = []


class Candidate(BaseModel):
    url: str | None = Field(default=None, description="the one candidate URL that lists open calls, or null")


@cache
def _prompt(name: str) -> str:
    text = (Path(__file__).parent / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    themes = "\n".join(f"- {code}: {label}" for code, label in VOCABULARY["themes"].items())
    return text.replace("{themes}", themes)


async def extract_calls(model, *, funder: str, url: str, text: str) -> list[Call]:
    reply = await model.with_structured_output(Calls, method="json_schema").ainvoke(
        [("system", _prompt("extract")), ("user", f"Funder: {funder}\nPage: {url}\n\n{text[:MAX_PAGE_CHARS]}")])
    return [c for c in reply.calls if len(c.title.strip()) >= 4]


async def pick_page(model, *, funder: str, candidates: list[tuple[str, str]]) -> str | None:
    """Of pages already found, the one most likely to list open calls; never a URL it was not given."""
    listing = "\n".join(f"- {url} | {title}" for url, title in candidates)
    reply = await model.with_structured_output(Candidate, method="json_schema").ainvoke(
        [("system", _prompt("pick")), ("user", f"Funder: {funder}\n\nCandidates:\n{listing}")])
    urls = {u for u, _ in candidates}
    return reply.url if reply.url in urls else None
