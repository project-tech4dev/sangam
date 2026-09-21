from datetime import date

from app.schemas.common import ReadModel


class ProgramOut(ReadModel):
    id: int
    org_id: int | None = None
    org_name: str | None = None
    funder_id: int | None = None
    funder_name: str | None = None
    name: str
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    details: dict = {}
    source_name: str | None = None
