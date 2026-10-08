from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_principal
from app.db.pool import PoolDep
from app.repositories import me as repo
from app.schemas.me import MembershipOut, MeOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut, summary="The signed-in user and their org roles")
async def get_me(pool: PoolDep, principal: Annotated[CurrentUser, Depends(get_principal)]) -> MeOut:
    rows = [] if principal.is_anonymous else await repo.list_memberships(pool, principal.id)
    return MeOut(
        id=principal.id,
        email=principal.email,
        is_staff=principal.is_staff,
        is_anonymous=principal.is_anonymous,
        memberships=[MembershipOut.model_validate(r) for r in rows],
    )
