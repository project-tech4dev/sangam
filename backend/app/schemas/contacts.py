from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import ReadModel

ContactKind = Literal["office_bearer", "programme", "grants", "other"]


class ContactOut(ReadModel):
    id: int
    org_id: int | None = None
    funder_id: int | None = None
    name: str
    role: str | None = None
    kind: str = "other"
    email: str | None = None
    phone: str | None = None
    verified: bool = False
    notes: str | None = None
    source_name: str | None = None
    fetched_at: datetime | None = None


class ContactCreate(BaseModel):
    org_id: int | None = None
    funder_id: int | None = None
    name: str = Field(min_length=1)
    role: str | None = None
    kind: ContactKind = "other"
    email: EmailStr | None = None
    phone: str | None = None
    verified: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def exactly_one_owner(self) -> "ContactCreate":
        if (self.org_id is None) == (self.funder_id is None):
            raise ValueError("exactly one of org_id or funder_id is required")
        return self


class ContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    role: str | None = None
    kind: ContactKind | None = None
    email: EmailStr | None = None
    phone: str | None = None
    verified: bool | None = None
    notes: str | None = None
