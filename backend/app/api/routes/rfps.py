from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.core.security import get_current_user, require_user
from app.db.pool import PoolDep
from app.repositories import rfps as repo
from app.schemas.common import Page
from app.schemas.rfps import Feed, RfpMatchOut, RfpMatchUpdate, RfpOut

router = APIRouter(prefix="/rfps", tags=["rfps"])


@router.get("", response_model=Page[RfpOut], summary="List funding opportunities")
async def list_rfps(
    pool: PoolDep,
    page: PageParams = Depends(),
    status: str | None = None,
    deadline_before: date | None = None,
    tag: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[RfpOut]:
    rows, total = await repo.list_rfps(
        pool, limit=page.limit, offset=page.offset,
        status=status, deadline_before=deadline_before.isoformat() if deadline_before else None,
        tag=tag,
    )
    return Page(items=[RfpOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/feed", response_model=Feed, summary="An org's open and saved calls")
async def feed(pool: PoolDep, user_id: UUID = Depends(require_user), org: str | None = None) -> Feed:
    """Without `org`, the caller's first organisation by name."""
    # Runs as the caller: another org's matches are filtered out by RLS, so its feed is empty.
    row = await repo.feed(pool, org)
    if row is None:
        raise HTTPException(404, f"org {org} not found" if org else "You are not a member of an organisation")
    return Feed(org_id=row["id"], org_slug=row["slug"], org_name=row["name"], can_act=row["can_act"],
                domains=row["domains"], last_pulled=row["last_pulled"], items=row["items"])


@router.get("/{rfp_id}", response_model=RfpOut, summary="Opportunity detail")
async def get_rfp(rfp_id: int, pool: PoolDep, user_id: UUID = Depends(get_current_user)) -> RfpOut:
    row = await repo.get_rfp(pool, rfp_id)
    if row is None:
        raise HTTPException(404, f"rfp {rfp_id} not found")
    return RfpOut.model_validate(row)


@router.get("/{rfp_id}/matches", response_model=list[RfpMatchOut],
            summary="Org matches flagged for an opportunity")
async def list_matches(
    rfp_id: int,
    pool: PoolDep,
    user_id: UUID = Depends(get_current_user),
) -> list[RfpMatchOut]:
    if await repo.get_rfp(pool, rfp_id) is None:
        raise HTTPException(404, f"rfp {rfp_id} not found")
    rows = await repo.list_matches(pool, rfp_id)
    return [RfpMatchOut.model_validate(r) for r in rows]


@router.patch("/{rfp_id}/matches/{org_id}", response_model=RfpMatchOut,
              summary="Save, review or dismiss a flagged match")
async def update_match(
    rfp_id: int,
    org_id: int,
    body: RfpMatchUpdate,
    pool: PoolDep,
    user_id: UUID = Depends(require_user),
) -> RfpMatchOut:
    row = await repo.update_match(
        pool, rfp_id, org_id,
        status=body.status, match_notes=body.match_notes, matched_by=str(user_id),
    )
    if row is None:
        raise HTTPException(404, f"match (rfp {rfp_id}, org {org_id}) not found")
    return RfpMatchOut.model_validate(row)
