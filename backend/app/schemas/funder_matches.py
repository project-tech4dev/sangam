from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.matching.rubric import Tier
from app.schemas.common import ReadModel


class RunOut(ReadModel):
    run_id: UUID
    run_at: datetime
    org_id: int
    rubric_version: str
    funders_checked: int
    tiers: dict[str, int]


class MatchOrg(ReadModel):
    id: int
    slug: str
    name: str


class MatchRun(ReadModel):
    run_id: UUID
    run_at: datetime
    rubric_version: str
    funders_checked: int
    earlier_runs: int


class MatchFunder(ReadModel):
    id: int
    slug: str
    name: str
    funder_type: str | None


class MatchReason(ReadModel):
    kind: Literal["fit", "gap"]
    criterion: str
    text: str


class MatchCard(ReadModel):
    reasons: list[MatchReason]


class MatchOut(ReadModel):
    id: int
    funder: MatchFunder
    score: int | None
    prev_score: int | None = Field(description="this funder's score in the run before; null when unscored or absent")
    tier: Tier
    card: MatchCard


class MatchListOut(ReadModel):
    org: MatchOrg
    may_run: bool
    run: MatchRun | None
    counts: dict[str, int]
    matches: list[MatchOut]


class MatchDetailOut(ReadModel):
    id: int
    run_at: datetime
    rubric_version: str
    detail: dict[str, Any]
