from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.db.pool import OwnerPoolDep, PoolDep
from app.repositories import access_check as repo
from app.schemas.access_check import (
    AccessCheckOut,
    FlagCountOut,
    FlagTableOut,
    FlagTablesOut,
    PublicTableOut,
    PublicTablesOut,
    TableAccessOut,
)

router = APIRouter(prefix="/access-check", tags=["access-check"])


@router.get(
    "",
    response_model=AccessCheckOut,
    summary="What the grants and RLS let the caller see in users, org_members, threads, proposals and rfp_matches",
)
async def access_check(pool: PoolDep) -> AccessCheckOut:
    identity = await repo.access_identity(pool)
    tables = []
    for table in repo.ACCESS_CHECK_TABLES:
        rows = await repo.access_rows(pool, table)
        tables.append(TableAccessOut(table=table, allowed=rows is not None, rows=rows or []))
    my_orgs = [] if identity["user_id"] is None else await repo.my_orgs(pool)
    return AccessCheckOut(**identity, my_orgs=my_orgs, tables=tables)


@router.get(
    "/public",
    response_model=PublicTablesOut,
    summary="The public tables as the caller: a count and the first rows of each",
)
async def access_check_public(pool: PoolDep, limit: Annotated[int, Query(ge=1, le=50)] = 5) -> PublicTablesOut:
    return await _sample(pool, repo.PUBLIC_TABLES, limit)


@router.get(
    "/staff",
    response_model=PublicTablesOut,
    summary="The staff-only Import tables as the caller: a count and the first rows of each",
)
async def access_check_staff(pool: PoolDep, limit: Annotated[int, Query(ge=1, le=50)] = 5) -> PublicTablesOut:
    return await _sample(pool, repo.STAFF_ONLY_TABLES, limit)


async def _sample(pool: PoolDep, groups: dict[str, list[str]], limit: int) -> PublicTablesOut:
    identity = await repo.access_identity(pool)
    tables = [
        PublicTableOut(group=group, **await repo.sample_table(pool, table, limit))
        for group, names in groups.items()
        for table in names
    ]
    return PublicTablesOut(db_role=identity["db_role"], is_staff=identity["is_staff"], tables=tables)


@router.get(
    "/flag",
    response_model=FlagTablesOut,
    summary="The public-by-flag tables: what the caller sees of each kind of row, against what exists",
)
async def access_check_flag(
    pool: PoolDep, owner: OwnerPoolDep, limit: Annotated[int, Query(ge=1, le=50)] = 15
) -> FlagTablesOut:
    identity = await repo.access_identity(pool)
    mine = await repo.my_org_ids(pool)
    tables = []
    for table in repo.FLAG_TABLES:
        seen = await repo.flag_counts(pool, table, mine)
        total = await repo.flag_counts(owner, table, mine)
        counts = [
            FlagCountOut(kind=kind, you_see=seen.get(kind, 0), in_table=total.get(kind, 0))
            for kind in repo.FLAG_KINDS
            if table != "org_identifiers" or kind != "funder, private"
        ]
        tables.append(FlagTableOut(table=table, counts=counts, rows=await repo.flag_rows(pool, table, mine, limit)))
    return FlagTablesOut(**identity, my_org_ids=mine, tables=tables)
