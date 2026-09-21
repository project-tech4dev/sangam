from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import get_pool
from app.repositories import programs as repo
from app.schemas.common import Page
from app.schemas.programs import ProgramOut

router = APIRouter(prefix="/programs", tags=["programs"])


@router.get("", response_model=Page[ProgramOut], summary="List programs")
async def list_programs(
    page: PageParams = Depends(),
    funder: str | None = None,
    org: str | None = None,
    status: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[ProgramOut]:
    rows, total = await repo.list_programs(
        get_pool(), limit=page.limit, offset=page.offset,
        funder=funder, org=org, status=status,
    )
    return Page(items=[ProgramOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/{program_id}", response_model=ProgramOut, summary="Program detail")
async def get_program(program_id: int, user_id: UUID = Depends(get_current_user)) -> ProgramOut:
    row = await repo.get_program(get_pool(), program_id)
    if row is None:
        raise HTTPException(404, f"program {program_id} not found")
    return ProgramOut.model_validate(row)
