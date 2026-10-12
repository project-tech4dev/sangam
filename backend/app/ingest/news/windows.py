"""Each subject's search window (D15) and what a run will cost (the plan line in 2b). Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.ingest.news.feeds import Subject, queries_for, scopes_for

NEWCOMER_DAYS = 90
# How long after publication Tavily may first index an item: small outlets and social posts often arrive late.
INDEX_GRACE_DAYS = 30


def window_days(searched_through: date | None, today: date) -> int:
    if searched_through is None:
        return NEWCOMER_DAYS
    return max(1, (today - searched_through).days + 1)


def stale_floor(searched_through: date | None, today: date) -> date:
    """Items published before this are old news for this subject: kept as scored links, never a story."""
    if searched_through is None:
        return today - timedelta(days=NEWCOMER_DAYS)
    return searched_through - timedelta(days=INDEX_GRACE_DAYS)


@dataclass(frozen=True)
class NewsPlan:
    subjects: int
    newcomers: int
    searches: int
    cost_usd: float


def plan(subjects: list[Subject], *, today: date, settings) -> NewsPlan:
    searches = sum(len(queries_for(s)) * len(scopes_for(s)) for s in subjects)
    cost = searches * settings.news_search_cost_usd + (
        searches * settings.news_links_per_search * settings.news_classify_cost_usd)
    return NewsPlan(
        subjects=len(subjects),
        newcomers=sum(s.searched_through is None for s in subjects),
        searches=searches,
        cost_usd=round(cost, 2),
    )
