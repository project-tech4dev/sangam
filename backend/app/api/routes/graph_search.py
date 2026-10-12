from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.security import get_current_user, require_staff, require_user
from app.integrations import graphiti
from app.repositories import graph_search as repo
from app.schemas.graph_search import (
    GROUP_PATTERN,
    GraphClearOut,
    GraphDocumentsIn,
    GraphDocumentsOut,
    GraphEpisodeIn,
    GraphEpisodeOut,
    GraphGroupOut,
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
STAFF = [Depends(require_staff)]


@router.get("/status", dependencies=[Depends(get_current_user)], response_model=GraphStatusOut,
            summary="Whether the knowledge graph is on")
async def graph_status() -> GraphStatusOut:
    status = graphiti.graph_status(get_settings())
    if status == "ok" and graphiti.client is None:
        status = "the graph failed to start"
    return GraphStatusOut(enabled=graphiti.client is not None, reason=status)


@router.post("/search", dependencies=[Depends(require_user)], response_model=GraphSearchOut,
             summary="Search facts in the graph (no model call)")
async def search_graph(
    body: GraphSearchIn,
    client: GraphDep,
) -> GraphSearchOut:
    facts = await repo.search(client, query=body.query, group_id=body.group_id, limit=body.limit)
    return GraphSearchOut(query=body.query, facts=facts)


@router.post("/episodes", dependencies=STAFF, response_model=GraphEpisodeOut,
             summary="Add text; entities and facts are extracted from it")
async def add_episode(
    body: GraphEpisodeIn,
    client: GraphDep,
) -> GraphEpisodeOut:
    result = await repo.add_episode(client, text=body.text, name=body.name,
                                    source_description=body.source_description, group_id=body.group_id)
    return GraphEpisodeOut(**result)


@router.post("/documents", dependencies=STAFF, response_model=GraphDocumentsOut,
             summary="Read files from Supabase Storage and add their text to the graph")
async def add_documents(
    body: GraphDocumentsIn,
    client: GraphDep,
) -> GraphDocumentsOut:
    if not get_settings().storage_enabled:
        raise HTTPException(503, "Supabase Storage is not configured: set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    result = await repo.add_documents(client, bucket=body.bucket, prefix=body.prefix, limit=body.limit,
                                      group_id=body.group_id or body.bucket)
    return GraphDocumentsOut(**result)


@router.post("/documents/stream", dependencies=STAFF,
             summary="Same as /documents, streamed as one JSON progress event per line")
async def stream_documents(body: GraphDocumentsIn, client: GraphDep) -> StreamingResponse:
    if not get_settings().storage_enabled:
        raise HTTPException(503, "Supabase Storage is not configured: set SUPABASE_URL and SUPABASE_SERVICE_KEY")

    async def lines():
        events = repo.documents_events(client, bucket=body.bucket, prefix=body.prefix, limit=body.limit,
                                       group_id=body.group_id or body.bucket)
        async for event in events:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.get("/groups", dependencies=STAFF, response_model=list[GraphGroupOut],
            summary="Every group in the graph, with its node and episode counts")
async def list_groups(client: GraphDep) -> list[GraphGroupOut]:
    return [GraphGroupOut(**g) for g in await repo.groups(client)]


@router.delete("", dependencies=STAFF, response_model=GraphClearOut,
               summary="Delete every node and fact, or one group's")
async def clear_graph(
    client: GraphDep,
    group_id: Annotated[str | None, Query(pattern=GROUP_PATTERN)] = None,
) -> GraphClearOut:
    deleted = await repo.clear(client, group_id=group_id)
    return GraphClearOut(group_id=group_id, nodes_deleted=deleted)
