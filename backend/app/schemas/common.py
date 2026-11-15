from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ReadModel(BaseModel):
    """Base for read models: rows come from dict_row SELECTs that may carry
    extra columns (e.g. the COUNT(*) OVER () window)."""

    model_config = ConfigDict(extra="ignore")


class Facet(BaseModel):
    value: str
    count: int  # rows that have this value


class FacetedPage(Page[T], Generic[T]):
    """A page for a list screen with bucket cards and dropdowns: their counts and options come with it."""

    counts: dict[str, int] = {}
    facets: dict[str, list[Facet]] = {}
