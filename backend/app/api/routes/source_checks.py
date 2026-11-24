from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import CurrentUser, require_staff
from app.db.pool import OwnerPoolDep
from app.repositories import source_checks as repo
from app.schemas.source_checks import (
    BaselineOut,
    BaselineSourceOut,
    CheckIn,
    CheckRunDetailOut,
    CheckRunOut,
    TrackedOut,
)

# Staff only, like source_checks; the check writes as the owner, as make source-check does.
router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_staff)])


@router.get("/tracked", response_model=list[TrackedOut],
            summary="Every organisation a change check can run on, with its tracked sources and last check")
async def list_tracked(pool: OwnerPoolDep) -> list[TrackedOut]:
    async with pool.connection() as conn:
        return [TrackedOut.model_validate(r) for r in await repo.list_tracked(conn)]


@router.get("/research/{slug}/baseline", response_model=BaselineOut,
            summary="The sources a change check would compare, and how many facts cite each")
async def check_baseline(slug: str, pool: OwnerPoolDep) -> BaselineOut:
    from app.ingest.refresh.service import baseline_view

    async with pool.connection() as conn:
        sources, unrecorded = await baseline_view(conn, slug)
        name = await repo.entity_name(conn, slug)
    return BaselineOut(slug=slug, name=name, unrecorded=unrecorded,
                       sources=[BaselineSourceOut.model_validate(s, from_attributes=True) for s in sources])


@router.get("/research/{slug}/checks", response_model=list[CheckRunOut], summary="One entity's change checks, newest first")
async def list_checks(slug: str, pool: OwnerPoolDep) -> list[CheckRunOut]:
    async with pool.connection() as conn:
        return [CheckRunOut.model_validate(r) for r in await repo.list_runs(conn, slug)]


@router.get("/checks/{run_id}", response_model=CheckRunDetailOut, summary="What one change check found, per source")
async def get_check(run_id: UUID, pool: OwnerPoolDep) -> CheckRunDetailOut:
    async with pool.connection() as conn:
        found = await repo.get_run(conn, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no change check {run_id}")
    return CheckRunDetailOut.model_validate(found)


@router.post("/research/{slug}/checks", response_model=CheckRunDetailOut,
             summary="Check one entity's sources for change, and save what it found")
async def run_check(slug: str, body: CheckIn, pool: OwnerPoolDep,
                    staff: CurrentUser = Depends(require_staff)) -> CheckRunDetailOut:
    from app.ingest.refresh.service import Busy, NoBaseline, run, update_refused

    if body.refresh and body.depth != "full":
        raise HTTPException(status_code=422, detail="an update needs the full check: it reads the judge's hints")
    if body.refresh and (why := await update_refused(pool, slug)):
        raise HTTPException(status_code=409, detail=why)
    try:
        run_id = await run(pool, slug, body.depth, body.refresh, staff.id, user_email=staff.email)
    except NoBaseline as exc:
        raise HTTPException(status_code=409, detail="Nothing to compare: no research of this organisation records "
                                                    "which versions it read. Research it once first.") from exc
    except Busy as exc:
        raise HTTPException(status_code=409, detail="A check of this organisation is already running.") from exc
    async with pool.connection() as conn:
        found = await repo.get_run(conn, run_id)
    return CheckRunDetailOut.model_validate(found)
