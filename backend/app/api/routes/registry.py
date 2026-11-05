from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import PageParams
from app.core.security import get_current_user
from app.db.pool import OwnerPoolDep, PoolDep
from app.repositories import registry as repo
from app.schemas.registry import RegistryOut, RegistryPage, RegistryRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("", response_model=RegistryOut, summary="Every org and funder the Registry lists, in one call")
async def registry(pool: PoolDep, owner: OwnerPoolDep,
                   user_id: Annotated[UUID, Depends(get_current_user)]) -> RegistryOut:
    rows = await repo.registry_rows(pool, owner)
    await _add_research(owner, rows)
    return RegistryOut(rows=[RegistryRow.model_validate(r) for r in rows])


@router.get("/page", response_model=RegistryPage, response_model_exclude={"items": {"__all__": {"search"}}},
            summary="One page of the Registry, filtered and searched, with the cards' counts and the dropdowns")
async def registry_page(
    pool: PoolDep, owner: OwnerPoolDep, user_id: Annotated[UUID, Depends(get_current_user)],
    page: Annotated[PageParams, Depends()],
    kind: Annotated[str, Query(alias="type")] = "all",
    theme: str = "all", population: str = "all", sdg: str = "all", where: str = "any",
    reg: str = "any", ftype: str = "all", approach: str = "any", q: str = "",
) -> RegistryPage:
    f = repo.Filters(kind={"cso": "org", "funder": "funder"}.get(kind, "all"), theme=theme, population=population,
                     sdg=sdg, where=where, reg=reg, ftype=ftype, approach=approach, q=q)
    out = repo.registry_page(await repo.registry_rows(pool, owner), f, limit=page.limit, offset=page.offset)
    await _add_research(owner, out["items"])  # the page's rows only, not the whole Registry
    return RegistryPage.model_validate(out)


async def _add_research(owner, rows: list[dict]) -> None:
    if not rows:
        return
    try:
        research = await repo.research_counts(owner, [(r["kind"], r["id"], r["slug"]) for r in rows])
    except Exception as exc:  # noqa: BLE001 - a research count is a hint on the row, not the list
        logger.warning("registry research counts failed: %s", exc)
        return
    for r in rows:
        hit = research.get((r["kind"], r["id"]))
        if hit:
            r["research_runs"], r["researched_on"] = hit["runs"], hit["latest"]
