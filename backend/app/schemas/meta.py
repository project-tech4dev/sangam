from app.schemas.common import ReadModel


class TagOut(ReadModel):
    id: int
    slug: str
    label: str
    kind: str = "sector"
    parent_id: int | None = None
    taxonomy_ref: str | None = None


class LocationOut(ReadModel):
    id: int
    kind: str
    name: str
    parent_id: int | None = None
    parent_name: str | None = None


class StatsOut(ReadModel):
    orgs: int
    funders: int
    grants: int
    fit_scores: int
    programs: int
    contacts: int
    documents: int
    news_stories: int
    districts_covered: int
