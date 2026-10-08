from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.common import ReadModel

Role = Literal["admin", "member", "steward"]


class OrgMemberOut(ReadModel):
    user_id: UUID
    display_name: str | None
    email: str
    role: Role


class OrgMemberAdd(BaseModel):
    email: EmailStr
    role: Role = "member"


class OrgMemberRole(BaseModel):
    role: Role
