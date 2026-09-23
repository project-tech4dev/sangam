from datetime import datetime

from app.schemas.common import ReadModel


class DocumentOut(ReadModel):
    # Metadata only — content_md is deliberately not exposed over the list API.
    id: int
    org_id: int | None = None
    funder_id: int | None = None
    title: str | None = None
    doc_type: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
