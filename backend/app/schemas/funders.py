from datetime import datetime

from app.schemas.common import ReadModel
from app.schemas.contacts import ContactOut
from app.schemas.orgs import IdentifierOut, LocationRef, TagRef


class FunderListItem(ReadModel):
    # Legacy-compat shape: field names are frozen (frontend reads them directly).
    id: int
    slug: str
    name: str
    funder_type: str | None = None
    website: str | None = None
    focus_sectors: list[str] = []     # computed: funder_tags labels
    geographies: list[str] = []       # computed: funder_locations names
    profile: dict = {}
    latest_scores: dict = {}          # {"v1": 93, "v2": 93} per rubric version


class GrantSummary(ReadModel):
    id: int
    org_name: str
    title: str
    status: str
    start_date: str | None = None
    end_date: str | None = None


class FunderDetail(FunderListItem):
    section_135_bound: bool | None = None
    identifiers: list[IdentifierOut] = []
    tags: list[TagRef] = []
    locations: list[LocationRef] = []
    contacts: list[ContactOut] = []
    source_name: str | None = None
    fetched_at: datetime | None = None


class FunderScoreRow(ReadModel):
    id: int
    org_name: str
    rubric_version: str
    total_score: int
    max_score: int
    scored_by: str
    scored_at: datetime
    notes: str | None = None
