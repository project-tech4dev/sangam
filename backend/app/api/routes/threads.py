from __future__ import annotations

from typing import Annotated
from uuid import UUID

from ag_ui_langgraph.utils import langchain_messages_to_agui
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.security import require_user
from app.db.pool import OwnerPoolDep, PoolDep
from app.repositories import threads as repo
from app.schemas.threads import ThreadMessagesOut, ThreadOut

router = APIRouter(prefix="/threads", tags=["threads"])

UserDep = Annotated[UUID, Depends(require_user)]


@router.get("", response_model=list[ThreadOut], summary="The caller's own chats, newest first")
async def list_threads(
    pool: PoolDep, user_id: UserDep
) -> list[ThreadOut]:
    rows = await repo.list_threads(pool, user_id=user_id)
    return [ThreadOut.model_validate(r) for r in rows]


@router.get("/{thread_id}/messages", response_model=ThreadMessagesOut, summary="One Ask chat's saved messages")
async def thread_messages(
    thread_id: str, request: Request, owner_pool: OwnerPoolDep, user_id: UserDep
) -> ThreadMessagesOut:
    # Owner pool: checkpoints are closed to callers, so access is decided here, before anything is read.
    if not await repo.can_open(owner_pool, thread_id=thread_id, user_id=user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    graph = getattr(request.app.state, "ask_graph", None)
    if graph is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent not loaded")
    # The graph, not the saver: messages are rebuilt from writes, and a raw checkpoint can hold none.
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    messages = langchain_messages_to_agui(state.values.get("messages", []))
    return ThreadMessagesOut(
        thread_id=thread_id,
        messages=[m.model_dump(mode="json", by_alias=True, exclude_none=True) for m in messages],
    )
