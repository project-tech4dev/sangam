from __future__ import annotations

from datetime import date

from pydantic import Field

from app.schemas.common import ReadModel
from app.schemas.documents import FileLinkOut
from app.schemas.news_stories import StoryOut
from app.schemas.partner_groups import PartnerGroupPage


class EntityRef(ReadModel):
    id: int
    name: str
    slug: str


class ProfileIdentifier(ReadModel):
    """A registration as every viewer sees it: a private one is on file, with no number or detail."""

    id: int | None = None
    id_type: str
    status: str
    is_current: bool = True
    number_withheld: bool = False
    id_value: str | None = None
    application_ref: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    check_method: str | None = None
    verified: bool = False
    source_type: str | None = None
    evidence: str | None = None
    source_url: str | None = None
    notes: str | None = None


class ProfileContact(ReadModel):
    id: int
    name: str
    role: str | None = None
    kind: str = "other"
    email: str | None = None
    phone: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class OrgIdentity(ReadModel):
    """The org's own row as its public page shows it; no Darpan or contact JSON passes through."""

    id: int
    slug: str
    name: str
    legal_form: str | None = None
    registration_date: date | None = None
    registered_address: str | None = None
    parent: EntityRef | None = None
    website: str | None = None
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    staff_count: int | None = None
    staff_count_note: str | None = None
    district: str | None = None       # registered location and its state
    state: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    identifiers: list[ProfileIdentifier] = Field(default_factory=list)
    contacts: list[ProfileContact] = Field(default_factory=list)


class FunderIdentity(ReadModel):
    id: int
    slug: str
    name: str
    funder_type: str | None = None
    website: str | None = None
    funding_trend: str | None = None
    legal_form: str | None = None
    founded_year: int | None = None
    registered_address: str | None = None
    registered_location: str | None = None
    parent: EntityRef | None = None
    cin: str | None = None
    section_135_bound: bool | None = None
    intake_mode: str | None = None
    funds_external: bool | None = None
    typical_duration_months: int | None = None
    grant_size_min: float | None = None
    grant_size_max: float | None = None
    aliases: list[str] = Field(default_factory=list)
    source_name: str | None = None
    source_url: str | None = None
    contacts: list[ProfileContact] = Field(default_factory=list)


class StoryCounts(ReadModel):
    """Public stories about the entity, press and social posts, counted in SQL."""

    press: int = 0
    social: int = 0
    posts_since: date | None = None


class TagNote(ReadModel):
    slug: str
    label: str
    kind: str | None = None
    role: str | None = None
    note: str | None = None
    parent_label: str | None = None   # a sub-theme's theme, for "Theme › Sub-theme"


class SdgRef(ReadModel):
    code: str
    label: str


class MetricOut(ReadModel):
    id: int
    name: str
    value: float | None = None
    target: float | None = None
    unit: str | None = None
    period: str | None = None
    stage: str | None = None
    method: str | None = None
    program_id: int | None = None
    place: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class ProgramNode(ReadModel):
    id: int
    name: str
    kind: str | None = None
    parent_id: int | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    source_name: str | None = None
    source_url: str | None = None
    tags: list[TagNote] = Field(default_factory=list)
    metrics: list[MetricOut] = Field(default_factory=list)


class PlaceOut(ReadModel):
    location_id: int
    kind: str
    name: str
    state: str | None = None          # a district's state, so the page can group by it
    role: str | None = None
    note: str | None = None
    program_id: int | None = None
    program_name: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class FinancialYear(ReadModel):
    fiscal_year: str
    total_income: float | None = None
    program_spend: float | None = None
    non_program_spend: float | None = None
    foreign_contribution: float | None = None
    foreign_unspent: float | None = None
    is_audited: bool | None = None
    source_name: str | None = None
    source_url: str | None = None


class DocumentLinkOut(ReadModel):
    program_id: int | None = None
    program_name: str | None = None
    fiscal_year: str | None = None
    pages: list[str] = Field(default_factory=list)


class ProfileDocument(ReadModel):
    id: int
    title: str | None = None
    doc_type: str | None = None
    as_of: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    links: list[DocumentLinkOut] = Field(default_factory=list)


class SpendLine(ReadModel):
    id: int
    program_id: int | None = None
    program_name: str | None = None
    fiscal_year: str
    amount: float | None = None       # INR; null means not public
    notes: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class CsrYear(ReadModel):
    fiscal_year: str
    prescribed_csr: float | None = None
    total_spent: float | None = None
    spent_on_projects: float | None = None
    unspent_transferred: float | None = None
    local_area_spent: float | None = None
    source_name: str | None = None
    source_url: str | None = None


class FootprintState(ReadModel):
    fiscal_year: str
    state: str | None = None
    districts: int = 0
    district_names: list[str] = Field(default_factory=list)
    source_name: str | None = None
    source_url: str | None = None


class StatedPlace(ReadModel):
    name: str
    kind: str | None = None
    state: str | None = None
    role: str | None = None
    note: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class EligibilityDoc(ReadModel):
    id: int
    title: str | None = None
    content_md: str | None = None
    source_name: str | None = None
    source_url: str | None = None


class OpenCall(ReadModel):
    id: int
    title: str
    url: str | None = None
    deadline: date | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    source_url: str | None = None


class ResearchSource(ReadModel):
    url: str
    first_read: date | None = None


class ResearchTrail(ReadModel):
    """How often Import researched the entity and the public pages it read; no finding is served."""

    runs: int = 0
    latest: date | None = None
    sources: list[ResearchSource] = Field(default_factory=list)


class ProfileFacts(ReadModel):
    """What both kinds of profile read from the catalog."""

    programs: list[ProgramNode] = Field(default_factory=list)
    metrics: list[MetricOut] = Field(default_factory=list)
    documents: list[ProfileDocument] = Field(default_factory=list)
    tags: list[TagNote] = Field(default_factory=list)
    sdgs: list[SdgRef] = Field(default_factory=list)
    stories: StoryCounts = Field(default_factory=StoryCounts)
    research: ResearchTrail = Field(default_factory=ResearchTrail)
    hidden_contacts: int = 0          # non-public contacts on file: a count, never a name


class OrgFacts(ProfileFacts):
    org: OrgIdentity
    places: list[PlaceOut] = Field(default_factory=list)
    financials: list[FinancialYear] = Field(default_factory=list)
    funders: PartnerGroupPage = Field(default_factory=PartnerGroupPage)   # first page, by funder


class FunderFacts(ProfileFacts):
    funder: FunderIdentity
    partners: PartnerGroupPage = Field(default_factory=PartnerGroupPage)  # first page, by partner
    spend: list[SpendLine] = Field(default_factory=list)
    csr_years: list[CsrYear] = Field(default_factory=list)
    footprint: list[FootprintState] = Field(default_factory=list)
    stated: list[StatedPlace] = Field(default_factory=list)
    eligibility: list[EligibilityDoc] = Field(default_factory=list)
    open_calls: list[OpenCall] = Field(default_factory=list)


class OrgProfile(OrgFacts):
    """Everything an organisation's profile page shows, in one response."""

    news: list[StoryOut] = Field(default_factory=list)
    brief: FileLinkOut | None = None


class FunderProfile(FunderFacts):
    """Everything a funder's profile page shows, in one response."""

    news: list[StoryOut] = Field(default_factory=list)
    brief: FileLinkOut | None = None


class BriefLinkOut(FileLinkOut):
    """A signed link to an entity's research brief, with the entity's own slug and name."""

    slug: str
    name: str

