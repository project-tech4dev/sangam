from datetime import datetime

from pydantic import BaseModel, Field

GROUP_PATTERN = r"^[a-zA-Z0-9_-]+$"  # graphiti's validate_group_id


class GraphStatusOut(BaseModel):
    enabled: bool
    reason: str


class GraphSearchIn(BaseModel):
    query: str = Field(min_length=1)
    group_id: str | None = Field(default=None, pattern=GROUP_PATTERN)
    limit: int = Field(default=10, ge=1, le=50)


class GraphFactOut(BaseModel):
    uuid: str
    fact: str
    valid_at: datetime | None = None
    invalid_at: datetime | None = None


class GraphSearchOut(BaseModel):
    query: str
    facts: list[GraphFactOut]


class GraphEpisodeIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    name: str = "api-episode"
    source_description: str = "added via api"
    group_id: str | None = Field(default=None, pattern=GROUP_PATTERN)


class GraphEpisodeOut(BaseModel):
    entities: list[str]
    facts: list[str]
