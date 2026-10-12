"""Classification (spec section 2, step 3): one structured model call per item and subject."""

from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.ingest.adapters.tavily_news import Hit
from app.ingest.news.feeds import FEEDS, Subject, profile_for

PROMPT_VERSION = "signals-v2"
Kind = Literal["news", "opinion", "press_release", "social_post", "event", "background", "other"]
Sector = Literal["livelihoods", "health", "education", "environment", "others"]
Score = Field(ge=0, le=1)


KINDS = ("news", "opinion", "press_release", "social_post", "event", "background", "other")
SECTORS = ("livelihoods", "health", "education", "environment", "others")
SIGNALS = ("grant", "partnership", "programme_result", "award", "governance_issue", "regulatory", "controversy",
           "open_call", "other")


def _one_of(allowed: tuple[str, ...], fallback: str):
    """A value outside the list becomes the fallback: losing the whole item to one stray word costs more."""
    return lambda v: v if v in allowed else fallback


def _day(v):
    """A year or a month is not a date; keep the item, drop the date."""
    if isinstance(v, str) and len(v) != 10:
        return None
    return v


def _sectors(v):
    return [x for x in (v or []) if x in SECTORS]


class Region(BaseModel):
    state: str | None = None
    district: str | None = None


class EntityVerdict(BaseModel):
    on_target: bool
    match: float = Score
    confidence: float = Score
    content_kind: Kind
    is_news: bool
    event_date: date | None = None
    stance: Literal["positive", "neutral", "negative"]
    signal_type: Literal["grant", "partnership", "programme_result", "award", "governance_issue", "regulatory",
                         "controversy", "open_call", "other"]
    region: Region = Region()
    sector_tags: list[Sector] = []
    summary: str

    _kind = field_validator("content_kind", mode="before")(_one_of(KINDS, "other"))
    _signal = field_validator("signal_type", mode="before")(_one_of(SIGNALS, "other"))
    _stance = field_validator("stance", mode="before")(_one_of(("positive", "neutral", "negative"), "neutral"))
    _date = field_validator("event_date", mode="before")(_day)
    _sector = field_validator("sector_tags", mode="before")(_sectors)


class TopicVerdict(BaseModel):
    on_target: bool
    match: float = Score
    confidence: float = Score
    topic: Literal["fcra", "csr_funding", "ngo_news", "other"]
    content_kind: Kind
    is_news: bool
    event_date: date | None = None
    scope: Literal["district", "state", "north_east", "national", "international"]
    region: Region = Region()
    sentiment: Literal["positive", "neutral", "negative"]
    registry_named: list[str] = []
    sector_tags: list[Sector] = []
    summary: str

    _kind = field_validator("content_kind", mode="before")(_one_of(KINDS, "other"))
    _topic = field_validator("topic", mode="before")(_one_of(("fcra", "csr_funding", "ngo_news", "other"), "other"))
    _scope = field_validator("scope", mode="before")(
        _one_of(("district", "state", "north_east", "national", "international"), "national"))
    _sentiment = field_validator("sentiment", mode="before")(_one_of(("positive", "neutral", "negative"), "neutral"))
    _date = field_validator("event_date", mode="before")(_day)
    _sector = field_validator("sector_tags", mode="before")(_sectors)


@cache
def _prompt(name: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _item(hit: Hit) -> str:
    return (f"Title: {hit.title}\nURL: {hit.url}\nPublished: {hit.published}\n\nText:\n"
            f"{(hit.text or hit.snippet)[:8000]}")


async def classify_entity(model, subject: Subject, hit: Hit) -> EntityVerdict:
    who = f"Organisation: {subject.name}. Who it is: {profile_for(subject)}"
    return await model.with_structured_output(EntityVerdict).ainvoke(
        [("system", _prompt("entity")), ("user", f"{who}\n\n{_item(hit)}")])


async def classify_topic(model, feed_key: str, hit: Hit, registry_names: list[str]) -> TopicVerdict:
    # A plain .replace: the prompt is prose, and a brace in it must not be read as a format field.
    system = _prompt("topic").replace("{registry}", ", ".join(registry_names) or "(none)")
    return await model.with_structured_output(TopicVerdict).ainvoke(
        [("system", system), ("user", f"Feed: {FEEDS[feed_key].label}\n\n{_item(hit)}")])


async def write_headline(model, *, platform: str, title: str | None, summary: str) -> str:
    reply = await model.ainvoke([("system", _prompt("headline")),
                                 ("user", f"Platform: {platform}\nRaw title: {title}\nSummary: {summary}")])
    return str(getattr(reply, "content", reply)).strip().strip('"')[:120]
