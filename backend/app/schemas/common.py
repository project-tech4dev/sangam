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
