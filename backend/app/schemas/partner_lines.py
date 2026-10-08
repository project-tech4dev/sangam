from datetime import date, datetime

from app.schemas.common import ReadModel


class PartnerLineOut(ReadModel):
    id: int                               # funder_activity.id, cited as [activity:N]
    funder_id: int
    funder_slug: str
    funder_name: str
    fiscal_year: str
    partner_name: str
    partner_org_id: int | None = None     # set only when the partner is an organisation Sangam holds
    partner_org_slug: str | None = None
    partner_org_name: str | None = None
    project_name: str | None = None
    program_id: int | None = None
    program_name: str | None = None
    amount: float | None = None           # INR; null means not public, never zero
    start_date: date | None = None
    end_date: date | None = None
    relationship_status: str | None = None
    notes: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
    fy_is_dated: bool = True              # false: fiscal_year is when the source was read, not a grant date
