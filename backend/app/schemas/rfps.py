from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ReadModel


class RfpOut(ReadModel):
    id: int
    funder_id: int | None = None
    funder_name: str | None = None
    title: str
    url: str | None = None
    status: str = "open"
    deadline: date | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    eligibility: dict = {}
    details: dict = {}
    source_name: str | None = None
    fetched_at: datetime | None = None


class RfpMatchOut(ReadModel):
    rfp_id: int
    org_id: int
    org_name: str | None = None
    match_score: float | None = None
    match_notes: str | None = None
    status: str = "flagged"
    matched_by: str | None = None
    matched_at: datetime | None = None


class RfpMatchUpdate(BaseModel):
    status: Literal["flagged", "saved", "reviewed", "dismissed"]
    match_notes: str | None = None


class FeedCall(ReadModel):
    rfp_id: int
    title: str
    funder_id: int | None = None
    funder_name: str | None = None
    url: str | None = None
    source_url: str | None = None
    deadline: date | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    call_status: str = "open"
    status: str = "flagged"
    places: list[str] = []
    themes: list[str] = []


class Feed(ReadModel):
    """can_act: may this caller save or dismiss (the org's members and admins, and staff, as RLS allows)."""

    org_id: int
    org_slug: str
    org_name: str
    can_act: bool = False
    domains: list[str] = []
    last_pulled: datetime | None = None
    items: list[FeedCall] = []
