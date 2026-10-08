from datetime import datetime

from app.schemas.common import ReadModel
from app.schemas.contacts import ContactOut
from app.schemas.orgs import LocationRef, TagRef


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
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None


class GrantSummary(ReadModel):
    id: int
    org_name: str
    title: str
    status: str
    start_date: str | None = None
    end_date: str | None = None


class FunderDetail(FunderListItem):
    section_135_bound: bool | None = None
    cin: str | None = None            # corporate funders only (0031)
    aliases: list[str] = []
    tags: list[TagRef] = []
    locations: list[LocationRef] = []
    contacts: list[ContactOut] = []


class FunderScoreRow(ReadModel):
    id: int
    org_name: str
    rubric_version: str
    total_score: int
    max_score: int
    scored_by: str
    scored_at: datetime
    notes: str | None = None
