from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import CallerScope, CurrentUser, free_question_limit, get_principal
from app.db.pool import PoolDep
from app.repositories import me as repo
from app.repositories import threads
from app.schemas.me import FreeQuestionsOut, MembershipOut, MeOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut, summary="The signed-in user and their org roles")
async def get_me(pool: PoolDep, principal: Annotated[CurrentUser, Depends(get_principal)]) -> MeOut:
    rows = [] if principal.is_anonymous else await repo.list_memberships(pool, principal.id)
    free = None
    if not principal.is_anonymous:
        scope = CallerScope(principal.id, principal.is_staff, {r["org_id"]: r["role"] for r in rows})
        if (limit := free_question_limit(scope)) is not None:
            free = FreeQuestionsOut(used=await threads.asked(pool, user_id=principal.id), limit=limit)
    return MeOut(
        id=principal.id,
        email=principal.email,
        is_staff=principal.is_staff,
        is_anonymous=principal.is_anonymous,
        memberships=[MembershipOut.model_validate(r) for r in rows],
        free_questions=free,
    )
