from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ReadModel


class FitScoreOut(ReadModel):
    id: int
    org_id: int
    org_name: str | None = None
    funder_id: int
    funder_name: str | None = None
    rubric_version: str | None = None
    total_score: int
    max_score: int
    scored_by: str = "manual"
    scored_at: datetime
    notes: str | None = None


class ScoreItemOut(ReadModel):
    code: str
    label: str
    points: int
    score: int
    justification: str | None = None


class AdjustmentOut(ReadModel):
    id: int
    fit_score_id: int
    criterion_id: int
    code: str | None = None
    old_score: int | None = None
    new_score: int | None = None
    reason: str
    adjusted_by: UUID | None = None
    adjusted_at: datetime | None = None


class FitScoreDetail(FitScoreOut):
    items: list[ScoreItemOut] = []
    adjustments: list[AdjustmentOut] = []


class AdjustmentCreate(BaseModel):
    criterion_id: int
    old_score: int | None = None
    new_score: int = Field(ge=0)
    reason: str = Field(min_length=1)
