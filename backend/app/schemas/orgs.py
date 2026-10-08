from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ReadModel
from app.schemas.contacts import ContactOut


class OrgListItem(ReadModel):
    # Legacy-compat shape: field names are frozen (frontend reads them directly).
    id: int
    slug: str
    name: str
    darpan_id: str | None = None      # computed: org_identifiers id_type='darpan'
    cohort: str | None = None
    state: str | None = None          # computed: registered location's parent
    district: str | None = None       # computed: registered location
    sectors: list[str] = Field(default_factory=list)  # computed: org_tags labels, primary first
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None


class IdentifierOut(ReadModel):
    id: int | None = None
    id_type: str
    id_value: str | None = None       # NULL while only applied for
    status: str
    valid_from: date | None = None
    valid_until: date | None = None
    application_ref: str | None = None
    check_method: str | None = None
    verified: bool = False            # legacy seed flag; status is the field to read
    is_current: bool = True
    source_type: str | None = None
    evidence: str | None = None
    source_url: str | None = None


class LocationRef(ReadModel):
    id: int
    kind: str
    name: str
    role: str | None = None


class TagRef(ReadModel):
    slug: str
    label: str
    role: str | None = None


class OrgDetail(OrgListItem):
    org_kind: str = "cso"
    legal_form: str | None = None
    registration_date: date | None = None
    website: str | None = None
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    staff_count: int | None = None
    staff_count_note: str | None = None
    source_type: str | None = None
    evidence: str | None = None
    contact: dict = Field(default_factory=dict)
    profile: dict = Field(default_factory=dict)
    identifiers: list[IdentifierOut] = Field(default_factory=list)
    tags: list[TagRef] = Field(default_factory=list)
    locations: list[LocationRef] = Field(default_factory=list)
    contacts: list[ContactOut] = Field(default_factory=list)
