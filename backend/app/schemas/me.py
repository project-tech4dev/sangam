from __future__ import annotations

from uuid import UUID

from app.schemas.common import ReadModel


class MembershipOut(ReadModel):
    org_id: int
    org_slug: str
    org_name: str
    role: str


class FreeQuestionsOut(ReadModel):
    used: int
    limit: int


class MeOut(ReadModel):
    id: UUID | None
    email: str | None
    is_staff: bool
    is_anonymous: bool
    memberships: list[MembershipOut] = []
    # Only for someone outside every organisation, who may ask `limit` Ask questions in all.
    free_questions: FreeQuestionsOut | None = None
