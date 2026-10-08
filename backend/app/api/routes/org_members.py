from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors

from app.core.security import require_user
from app.db.pool import PoolDep
from app.repositories import org_members as repo
from app.schemas.org_members import OrgMemberAdd, OrgMemberOut, OrgMemberRole

router = APIRouter(prefix="/orgs/{org_id}/members", tags=["orgs"], dependencies=[Depends(require_user)])


def _message(exc: errors.Error) -> str:
    return exc.diag.message_primary or str(exc)


@asynccontextmanager
async def _refusals() -> AsyncIterator[None]:
    """The management functions' errors as HTTP, keeping their message for the person who hit them."""
    try:
        yield
    except errors.InsufficientPrivilege as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _message(exc)) from exc
    except errors.NoDataFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _message(exc)) from exc
    except errors.RaiseException as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _message(exc)) from exc
    except errors.UniqueViolation as exc:
        # Two admins adding the same person to two orgs at once: both checks pass, the index stops one.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That person is already an admin or member of another organisation."
        ) from exc


@router.get("", response_model=list[OrgMemberOut], summary="The org's members you may see")
async def list_members(org_id: int, pool: PoolDep) -> list[OrgMemberOut]:
    return [OrgMemberOut.model_validate(r) for r in await repo.list_members(pool, org_id)]


@router.post("", response_model=list[OrgMemberOut], status_code=201,
             summary="Add an existing user by email (org admins and staff)")
async def add_member(org_id: int, body: OrgMemberAdd, pool: PoolDep) -> list[OrgMemberOut]:
    async with _refusals():
        await repo.add_member(pool, org_id, body.email, body.role)
    return await list_members(org_id, pool)


@router.patch("/{user_id}", response_model=list[OrgMemberOut], summary="Change a member's role (org admins and staff)")
async def set_role(org_id: int, user_id: UUID, body: OrgMemberRole, pool: PoolDep) -> list[OrgMemberOut]:
    async with _refusals():
        await repo.set_role(pool, org_id, user_id, body.role)
    return await list_members(org_id, pool)


@router.delete("/{user_id}", response_model=list[OrgMemberOut], summary="Remove a member (org admins and staff)")
async def remove_member(org_id: int, user_id: UUID, pool: PoolDep) -> list[OrgMemberOut]:
    async with _refusals():
        await repo.remove_member(pool, org_id, user_id)
    return await list_members(org_id, pool)
