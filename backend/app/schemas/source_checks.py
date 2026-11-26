from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BaselineSourceOut(BaseModel):
    url: str
    kind: str | None
    snapshot_id: int
    read_on: str
    archived: bool
    facts: int


class BaselineOut(BaseModel):
    slug: str
    name: str | None = Field(None, description="the entity's name from its newest research")
    sources: list[BaselineSourceOut]
    unrecorded: int = Field(description="research rows saved before snapshots existed; their sources are not checked")


class CheckIn(BaseModel):
    depth: Literal["free", "full"] = Field(
        description="free: fetch, compare, diff and evidence, no model. full: also the judge and new-source search")
    refresh: bool = Field(False, description="full only: when the decision is refresh, save a partial update")


class EvidenceOut(BaseModel):
    verdict: str
    sentence: str


class SourceCheckOut(BaseModel):
    url: str
    status: str
    detail: str | None
    findings_intact: int
    findings_broken: int
    findings_unanchored: int
    judge: dict[str, Any] | None
    removed_text: list[str]
    added_text: list[str]
    evidence: list[EvidenceOut] | None
    baseline_snapshot_id: int | None
    new_snapshot_id: int | None
    baseline_seen_at: datetime | None
    baseline_hash: str | None = None
    today_hash: str | None = None


class CheckRunOut(BaseModel):
    run_id: UUID
    slug: str
    depth: str
    decision: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    refresh_row_id: int | None
    refresh_summary: str | None
    requested_by: str | None
    sources: int


class CheckRunDetailOut(CheckRunOut):
    checks: list[SourceCheckOut]


class TrackedOut(BaseModel):
    slug: str = Field(description="the research slug, which the change check runs on")
    kind: str
    id: int = Field(description="the org or funder row the research was saved to, as the Registry lists it")
    sources: int
    last_checked: datetime | None
