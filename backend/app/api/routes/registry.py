from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.db.pool import OwnerPoolDep, PoolDep
from app.repositories import registry as repo
from app.schemas.registry import RegistryOut, RegistryRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("", response_model=RegistryOut, summary="Every org and funder the Registry lists, in one call")
async def registry(pool: PoolDep, owner: OwnerPoolDep,
                   user_id: Annotated[UUID, Depends(get_current_user)]) -> RegistryOut:
    rows = await repo.registry_rows(pool, owner)
    try:
        research = await repo.research_counts(owner, [(r["kind"], r["id"], r["slug"]) for r in rows])
    except Exception as exc:  # noqa: BLE001 - a research count is a hint on the row, not the list
        logger.warning("registry research counts failed: %s", exc)
        research = {}
    for r in rows:
        hit = research.get((r["kind"], r["id"]))
        if hit:
            r["research_runs"], r["researched_on"] = hit["runs"], hit["latest"]
    return RegistryOut(rows=[RegistryRow.model_validate(r) for r in rows])
