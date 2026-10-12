"""D5 and D6: what is listed, what is public, and how a score reads. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Visibility = Literal["public", "listed", "hidden"]


@dataclass(frozen=True)
class Bars:
    listed_match: float
    listed_confidence: float
    public_match: float
    public_confidence: float
    negative_match: float
    negative_confidence: float
    topic_match: float = 0.75  # a topic story has no organisation to vouch for it, so it needs a surer match

    @classmethod
    def from_settings(cls, s) -> Bars:
        return cls(s.news_listed_match, s.news_listed_confidence, s.news_public_match, s.news_public_confidence,
                   s.news_negative_match, s.news_negative_confidence, s.news_topic_match)


def visibility(match: float, confidence: float, *, sentiment: str | None, is_news: bool, bars: Bars,
               dated: bool = True) -> Visibility:
    # A directory page, profile or old report with no date is background noise, not a signal.
    if not is_news and not dated:
        return "hidden"
    if sentiment == "negative":
        public = match >= bars.negative_match and confidence >= bars.negative_confidence
    else:
        public = match >= bars.public_match and confidence >= bars.public_confidence
    if public and is_news:
        return "public"
    if match >= bars.listed_match and confidence >= bars.listed_confidence:
        return "listed"
    return "hidden"


def topic_visibility(match: float, confidence: float, *, is_news: bool, dated: bool, scope: str | None,
                     bars: Bars) -> Visibility:
    """A topic story has no organisation to vouch for it, so only dated news about India is listed."""
    clears = match >= bars.topic_match and confidence >= bars.listed_confidence
    return "listed" if clears and is_news and dated and scope != "international" else "hidden"


def level(value: float, kind: Literal["match", "confidence"]) -> str:
    high, medium = (0.8, 0.6) if kind == "match" else (0.9, 0.8)
    return "High" if value >= high else "Medium" if value >= medium else "Low"
