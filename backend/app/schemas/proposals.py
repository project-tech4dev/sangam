from __future__ import annotations

from datetime import datetime
from typing import Any

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


class ProposalTab(ReadModel):
    key: str
    label: str
    question: str


class ProposalOut(ProposalItem):
    thread_id: str | None
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


class SavedOut(BaseModel):
    summary: dict[str, Any]
    work: dict[str, Any]
