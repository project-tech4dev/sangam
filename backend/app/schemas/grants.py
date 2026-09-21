from datetime import date, datetime

from app.schemas.common import ReadModel


class GrantOut(ReadModel):
    id: int
    funder_id: int
    funder_name: str | None = None
    org_id: int
    org_name: str | None = None
    program_id: int | None = None
    program_name: str | None = None
    title: str
    amount: float | None = None
    currency: str = "INR"
    start_date: date | None = None
    end_date: date | None = None
    status: str
    outcomes: dict = {}
    notes: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
