"""Shared router dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel


class PageParams(BaseModel):
    limit: Annotated[int, Query(ge=1, le=100)] = 50
    offset: Annotated[int, Query(ge=0)] = 0


class LegacyPageParams(BaseModel):
    """The two legacy array endpoints (/orgs, /funders) default to 'everything'
    so the existing frontend keeps receiving the full list."""

    limit: Annotated[int, Query(ge=1, le=500)] = 500
    offset: Annotated[int, Query(ge=0)] = 0
