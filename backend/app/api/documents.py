from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import PoolDep
from app.repositories import documents as repo
from app.schemas.common import Page
from app.schemas.documents import DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=Page[DocumentOut], summary="Document metadata (the vault)")
async def list_documents(
    pool: PoolDep,
    page: PageParams = Depends(),
    org: str | None = None,
    funder: str | None = None,
    doc_type: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[DocumentOut]:
    rows, total = await repo.list_documents(pool, limit=page.limit, offset=page.offset,
                                            org=org, funder=funder, doc_type=doc_type)
    return Page(items=[DocumentOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)
