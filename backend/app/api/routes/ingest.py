from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.ingest.sources import SOURCES
from app.repositories import ingest as repo
from app.schemas.ingest import QueueItemOut, RunItemOut, RunOut, SourceOut

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/sources", response_model=list[SourceOut], summary="Import sources and access rules")
async def list_sources(user_id: UUID = Depends(get_current_user)) -> list[SourceOut]:
    return [
        SourceOut(
            key=s.key, name=s.name, host=s.host, access_rule=s.access_rule.value, basis=s.basis,
            yields=list(s.yields), dispatchable=s.dispatchable,
            robots_checked_at=s.robots_checked_at.isoformat() if s.robots_checked_at else None,
        )
        for s in SOURCES.values()
    ]


@router.get("/runs", response_model=list[RunOut], summary="Recent import runs")
async def list_runs(pool: PoolDep, limit: int = 10,
                    user_id: UUID = Depends(get_current_user)) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in await repo.list_runs(pool, limit=limit)]


@router.get("/runs/{run_id}", response_model=list[RunItemOut], summary="What one run did")
async def run_items(run_id: int, pool: PoolDep,
                    user_id: UUID = Depends(get_current_user)) -> list[RunItemOut]:
    if await repo.get_run(pool, run_id) is None:
        raise HTTPException(status_code=404, detail=f"no import run {run_id}")
    return [RunItemOut.model_validate(r) for r in await repo.list_items(pool, run_id)]


@router.get("/queue", response_model=list[QueueItemOut], summary="Names awaiting review")
async def queue(pool: PoolDep, limit: int = 50,
                user_id: UUID = Depends(get_current_user)) -> list[QueueItemOut]:
    return [QueueItemOut.model_validate(r) for r in await repo.list_queue(pool, limit=limit)]
