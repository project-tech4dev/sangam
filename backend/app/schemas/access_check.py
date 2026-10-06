from __future__ import annotations

from typing import Any
from uuid import UUID

from app.schemas.common import ReadModel


class TableAccessOut(ReadModel):
    table: str
    allowed: bool
    rows: list[dict[str, Any]] = []


class AccessCheckOut(ReadModel):
    db_role: str
    user_id: UUID | None
    is_staff: bool
    my_orgs: list[dict[str, Any]] = []
    tables: list[TableAccessOut]


class PublicTableOut(TableAccessOut):
    group: str
    count: int


class PublicTablesOut(ReadModel):
    db_role: str
    is_staff: bool
    tables: list[PublicTableOut]


class FlagCountOut(ReadModel):
    kind: str
    you_see: int
    in_table: int


class FlagTableOut(ReadModel):
    table: str
    counts: list[FlagCountOut]
    rows: list[dict[str, Any]] = []


class FlagTablesOut(ReadModel):
    db_role: str
    is_staff: bool
    my_org_ids: list[int]
    tables: list[FlagTableOut]
