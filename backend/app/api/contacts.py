from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import get_pool
from app.repositories import contacts as repo
from app.schemas.common import Page
from app.schemas.contacts import ContactCreate, ContactOut, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactOut], summary="List contacts")
async def list_contacts(
    page: PageParams = Depends(),
    org: str | None = None,
    funder: str | None = None,
    kind: str | None = None,
    verified: bool | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[ContactOut]:
    rows, total = await repo.list_contacts(
        get_pool(), limit=page.limit, offset=page.offset,
        org=org, funder=funder, kind=kind, verified=verified,
    )
    return Page(items=[ContactOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/{contact_id}", response_model=ContactOut, summary="Contact detail")
async def get_contact(contact_id: int, user_id: UUID = Depends(get_current_user)) -> ContactOut:
    row = await repo.get_contact(get_pool(), contact_id)
    if row is None:
        raise HTTPException(404, f"contact {contact_id} not found")
    return ContactOut.model_validate(row)


@router.post("", response_model=ContactOut, status_code=201, summary="Create a contact")
async def create_contact(body: ContactCreate, user_id: UUID = Depends(get_current_user)) -> ContactOut:
    row = await repo.create_contact(get_pool(), body.model_dump())
    if row is None:
        raise HTTPException(404, "referenced org or funder not found")
    return ContactOut.model_validate(row)


@router.patch("/{contact_id}", response_model=ContactOut, summary="Update a contact")
async def update_contact(
    contact_id: int, body: ContactUpdate, user_id: UUID = Depends(get_current_user)
) -> ContactOut:
    if await repo.get_contact(get_pool(), contact_id) is None:
        raise HTTPException(404, f"contact {contact_id} not found")
    row = await repo.update_contact(get_pool(), contact_id, body.model_dump(exclude_unset=True))
    return ContactOut.model_validate(row)
