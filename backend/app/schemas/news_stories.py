"""Stories as the screens read them. Scores leave only as High, Medium or Low (D6), never as numbers."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class LinkOut(BaseModel):
    url: str
    host: str
    source_type: str


class StoryEntityOut(BaseModel):
    kind: str
    id: int
    slug: str
    name: str
    stance: str | None = None
    visibility: str
    match_level: str
    confidence_level: str


class StoryOut(BaseModel):
    id: int
    headline: str
    headline_generated: bool
    summary: str | None = None
    published_on: date | None = None
    date_source: str | None = None
    content_kind: str | None = None
    is_news: bool
    scope: str | None = None
    topic: str
    sentiment: str | None = None
    main_url: str | None = None
    main_host: str | None = None
    source_type: str | None = None
    visibility: str | None = None
    match_level: str
    confidence_level: str
    also: list[LinkOut] = []
    entities: list[StoryEntityOut] = []
    places: list[str] = []
    area_reason: str | None = None  # General only: why the story is in the reader's area
    row_id: int  # the entity link's id in the org and funder buckets, the story's in General
    about: StoryEntityOut | None = None  # org and funder buckets: the entity this row is a link of


class StoryCounts(BaseModel):
    org: int
    funder: int
    general: int


class StoryPage(BaseModel):
    items: list[StoryOut]
    next_cursor: str | None = None
    counts: StoryCounts | None = None
    last_pull: date | None = None


class HideIn(BaseModel):
    org_id: int | None = None
    funder_id: int | None = None
