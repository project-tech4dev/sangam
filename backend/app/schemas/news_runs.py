"""Scout's approval card for a news pull: what it would search, and which names it found."""

from __future__ import annotations

from pydantic import BaseModel


class NewsPlanOut(BaseModel):
    everyone: bool
    subjects: int
    records: int = 0  # the organisations and funders among the subjects, without the topic feeds
    newcomers: int
    searches: int
    cost_usd: float
    matched: list[str] = []
    unmatched: list[str] = []
