from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import CurrentUser, require_principal
from app.db.pool import OwnerPoolDep, PoolDep
from app.matching import service
from app.repositories import funder_matches as repo
from app.schemas.funder_matches import RunOut

router = APIRouter(prefix="/funder-matches", tags=["funder-matches"])


@router.post("/runs", response_model=RunOut, status_code=201, summary="Run and save a match for an org")
async def create_run(
    org: str,
    pool: PoolDep,
    owner: OwnerPoolDep,
    principal: Annotated[CurrentUser, Depends(require_principal)],
) -> RunOut:
    found = await repo.find_org(pool, org)
    if found is None:
        raise HTTPException(404, f"org {org} not found")
    if not found["may_run"]:
        raise HTTPException(403, "Running a match is for the org's stewards, admins and Sangam staff")
    return RunOut.model_validate(await service.run_and_save(owner, pool, found["id"], principal.id))
