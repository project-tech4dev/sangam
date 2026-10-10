from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.common import ReadModel


class RunOut(ReadModel):
    run_id: UUID
    run_at: datetime
    org_id: int
    rubric_version: str
    funders_checked: int
    tiers: dict[str, int]
