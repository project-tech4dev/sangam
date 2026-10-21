from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ReadModel


class ProposalOrg(ReadModel):
    id: int
    slug: str
    name: str


class ProposalFunder(ReadModel):
    id: int
    slug: str
    name: str


class ProposalItem(ReadModel):
    id: int
    title: str
    org: ProposalOrg
    funder: ProposalFunder
    fit_score: int | None
    created_at: datetime
    updated_at: datetime
    summary: dict[str, Any]
    can_edit: bool = Field(description="whether the caller may change it: the org's admins and stewards, and staff")


class ProposalSection(ReadModel):
    code: str
    label: str
    question: str
    tab: str
    strong: list[str]
    weak: str
    must_score_2: bool = False
    last: bool = Field(False, description="written last, from the finished parts")
    step: int = Field(4, description="the step it is written on: 3, Make a case, or 4, Make a plan")


class ProposalTab(ReadModel):
    key: str
    label: str
    step: int = 4


class ProposalOut(ProposalItem):
    thread_id: str = Field(description="the caller's own chat about this proposal; teammates each have theirs")
    work: dict[str, Any]
    sections: list[ProposalSection]
    tabs: list[ProposalTab]


class ProposalCreateIn(BaseModel):
    org: str = Field(description="the org's slug or id")
    funder_id: int
    title: str = Field(min_length=1, max_length=200)


class ProposalCreatedOut(BaseModel):
    id: int


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class WorkPatchIn(BaseModel):
    set: dict[str, Any] = Field(description='paths to new values, e.g. {"gates.csr1": "will_have"}')
    rev: dict[str, int] = Field(default_factory=dict, description="each changed section's rev, as it was read")


class VersionIn(BaseModel):
    shape: Literal["sangam", "form"] = Field("sangam", description="sangam: Sangam's parts; form: the funder's form")


class ResearchAnglesOut(BaseModel):
    angles: list[str] = Field(description="What research would look into, a few words each, for the person to edit.")
    dropped: list[str] = Field(default_factory=list, description="Angles left out for naming the org, a partner or a person.")


class SavedOut(BaseModel):
    summary: dict[str, Any]
    work: dict[str, Any]
