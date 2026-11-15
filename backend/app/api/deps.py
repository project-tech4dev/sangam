"""Shared router dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from app.schemas.common import Page


class PageParams(BaseModel):
    limit: Annotated[int, Query(ge=1, le=100)] = 50
    offset: Annotated[int, Query(ge=0)] = 0

    def build_page[M: BaseModel](self, rows: list[dict], total: int, model: type[M]) -> Page[M]:
        """The response for this request: each row read as `model`, with the total and this limit and offset."""
        items = [model.model_validate(row) for row in rows]
        return Page[model](items=items, total=total, limit=self.limit, offset=self.offset)


class LegacyPageParams(BaseModel):
    """The two legacy array endpoints (/orgs, /funders) default to 'everything'
    so the existing frontend keeps receiving the full list."""

    limit: Annotated[int, Query(ge=1, le=500)] = 500
    offset: Annotated[int, Query(ge=0)] = 0
