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
