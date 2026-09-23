from datetime import datetime

from app.schemas.common import ReadModel


class NewsOut(ReadModel):
    id: int
    url: str
    title: str | None = None
    domain: str | None = None
    seendate: datetime | None = None
    topic: str | None = None
    org_id: int | None = None
    funder_id: int | None = None
    source_name: str = "gdelt"


class StatsOut(ReadModel):
    orgs: int
    funders: int
    grants: int
    fit_scores: int
    programs: int
    contacts: int
    documents: int
    news_mentions: int
    districts_covered: int
