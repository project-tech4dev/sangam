from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.core.security import CurrentUser, get_current_user, require_staff, require_user
from app.integrations import graphiti
from app.repositories import graph_search as repo
from app.schemas.graph_search import (
    GROUP_PATTERN,
    GraphClearOut,
    GraphEpisodeIn,
    GraphEpisodeOut,
    GraphSearchIn,
    GraphSearchOut,
    GraphStatusOut,
)

router = APIRouter(prefix="/graph", tags=["graph"])


def graph_client():
    if graphiti.client is None:
        status = graphiti.graph_status(get_settings())
        reason = status if status != "ok" else "the graph failed to start"
        raise HTTPException(503, f"Knowledge graph unavailable: {reason}")
    return graphiti.client


GraphDep = Annotated[Any, Depends(graph_client)]


@router.get("/status", response_model=GraphStatusOut, summary="Whether the knowledge graph is on")
async def graph_status(user_id: Annotated[UUID | None, Depends(get_current_user)]) -> GraphStatusOut:
    status = graphiti.graph_status(get_settings())
    if status == "ok" and graphiti.client is None:
        status = "the graph failed to start"
    return GraphStatusOut(enabled=graphiti.client is not None, reason=status)


@router.post("/search", response_model=GraphSearchOut, summary="Search facts in the graph (no model call)")
async def search_graph(
    body: GraphSearchIn,
    client: GraphDep,
    user_id: Annotated[UUID, Depends(require_user)],
) -> GraphSearchOut:
    facts = await repo.search(client, query=body.query, group_id=body.group_id, limit=body.limit)
    return GraphSearchOut(query=body.query, facts=facts)


@router.post("/episodes", response_model=GraphEpisodeOut, summary="Add text; entities and facts are extracted from it")
async def add_episode(
    body: GraphEpisodeIn,
    client: GraphDep,
    principal: Annotated[CurrentUser, Depends(require_staff)],
) -> GraphEpisodeOut:
    result = await repo.add_episode(client, text=body.text, name=body.name,
                                    source_description=body.source_description, group_id=body.group_id)
    return GraphEpisodeOut(**result)


@router.delete("", response_model=GraphClearOut, summary="Delete every node and fact, or one group's")
async def clear_graph(
    client: GraphDep,
    principal: Annotated[CurrentUser, Depends(require_staff)],
    group_id: Annotated[str | None, Query(pattern=GROUP_PATTERN)] = None,
) -> GraphClearOut:
    deleted = await repo.clear(client, group_id=group_id)
    return GraphClearOut(group_id=group_id, nodes_deleted=deleted)
