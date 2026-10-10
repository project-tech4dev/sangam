from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import CurrentUser, require_principal
from app.db.pool import OwnerPoolDep, PoolDep
from app.matching import service
from app.matching.rubric import tier
from app.repositories import funder_matches as repo
from app.schemas.funder_matches import MatchDetailOut, MatchListOut, RunOut

router = APIRouter(prefix="/funder-matches", tags=["funder-matches"])
TIERS = ("strong", "medium", "weak", "not_scored")


@router.get("", response_model=MatchListOut, summary="An org's latest run, ranked by score")
async def list_matches(
    org: str, pool: PoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> MatchListOut:
    found = await repo.find_org(pool, org)
    # Not a member: 404, so a stranger cannot tell an unrun org from a hidden one.
    if found is None or not found["may_read"]:
        raise HTTPException(404, f"org {org} not found")
    run = await repo.latest_run(pool, found["id"])
    rows = await repo.list_matches(pool, run["run_id"], run["prev_run_id"]) if run else []
    matches = [{**r, "tier": tier(r["score"]),
                "funder": {"id": r["funder_id"], "slug": r["funder_slug"], "name": r["funder_name"],
                           "funder_type": r["funder_type"]}} for r in rows]
    counts = {t: sum(m["tier"] == t for m in matches) for t in TIERS}
    return MatchListOut.model_validate(
        {"org": found, "may_run": found["may_run"], "run": run, "counts": counts, "matches": matches}
    )


@router.get("/{match_id}/detail", response_model=MatchDetailOut, summary="One match's full reasoning")
async def match_detail(
    match_id: int, pool: PoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> MatchDetailOut:
    row = await repo.get_detail(pool, match_id)
    if row is None:
        raise HTTPException(404, f"match {match_id} not found")
    return MatchDetailOut.model_validate(row)


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
