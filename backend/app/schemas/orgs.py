from datetime import date, datetime

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
    sectors: list[str] = []           # computed: org_tags labels, primary first
    source_name: str | None = None
    fetched_at: datetime | None = None


class IdentifierOut(ReadModel):
    id_type: str
    id_value: str
    verified: bool = False
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
    contact: dict = {}
    profile: dict = {}
    identifiers: list[IdentifierOut] = []
    tags: list[TagRef] = []
    locations: list[LocationRef] = []
    contacts: list[ContactOut] = []
