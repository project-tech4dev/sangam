from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.integrations.graph_ontology import DEFAULT_GROUP

GROUP_PATTERN = r"^[a-zA-Z0-9_-]+$"  # graphiti's validate_group_id
EntityTypeName = Literal[
    "Organization", "Funder", "GovernmentBody", "Program", "Scheme", "Location", "Theme", "PopulationGroup",
    "Person",
]


class GraphStatusOut(BaseModel):
    enabled: bool
    reason: str


class GraphSearchIn(BaseModel):
    query: str = Field(min_length=1)
    group_id: str | None = Field(default=None, pattern=GROUP_PATTERN)
    limit: int = Field(default=10, ge=1, le=50)
    types: list[EntityTypeName] | None = Field(default=None, description="only facts between these entity types")


class GraphEntityOut(BaseModel):
    name: str
    type: str
    sangam_id: str | None = None


class GraphFactOut(BaseModel):
    uuid: str
    fact: str
    name: str
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    source: GraphEntityOut | None = None
    target: GraphEntityOut | None = None


class GraphSearchOut(BaseModel):
    query: str
    facts: list[GraphFactOut]


class GraphEpisodeIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    name: str = "api-episode"
    source_description: str = "added via api"
    group_id: str = Field(default=DEFAULT_GROUP, pattern=GROUP_PATTERN)


class GraphEpisodeOut(BaseModel):
    entities: list[GraphEntityOut]
    facts: list[str]
    dropped_facts: list[str] = Field(description="facts outside the ontology, deleted after extraction")
    unmapped: list[str] = Field(default=[], description="themes, schemes or groups the taxonomy does not name, labelled Unmapped")


class GraphCatalogIn(BaseModel):
    group_id: str = Field(default=DEFAULT_GROUP, pattern=GROUP_PATTERN)


class GraphCatalogOut(BaseModel):
    group_id: str
    nodes: int
    edges: int
    added_nodes: int
    added_edges: int
    removed_nodes: int
    removed_edges: int
    by_type: dict[str, int]


class GraphGroupOut(BaseModel):
    group_id: str
    nodes: int
    episodes: int


class GraphClearOut(BaseModel):
    group_id: str | None
    nodes_deleted: int


class GraphDocumentsIn(BaseModel):
    bucket: Literal["org-vault", "source-archive", "staff-sources"] = "org-vault"
    prefix: str = ""
    limit: int = Field(default=5, ge=1, le=50)
    group_id: str = Field(default=DEFAULT_GROUP, pattern=GROUP_PATTERN)


class GraphChunkOut(BaseModel):
    index: int
    chars: int
    status: Literal["added", "skipped"]
    entities: list[GraphEntityOut]
    facts: list[str]
    dropped_facts: list[str] = []
    unmapped: list[str] = []


class GraphDocumentOut(BaseModel):
    key: str
    status: Literal["added", "skipped", "failed"]
    chunks: int
    entities: int
    facts: int
    dropped_facts: int = 0
    reason: str | None = None
    parts: list[GraphChunkOut] = []


class GraphDocumentsOut(BaseModel):
    bucket: str
    prefix: str
    group_id: str
    found: int
    files: list[GraphDocumentOut]
