"""Answers a question asked mid-run from the run's state, without touching the running graph."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from importlib.resources import files
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from app.agent.models import resolve_model
from app.core.config import Settings
from app.schemas.ingest import AskLiveIn, AskLiveOut

PROMPT = (files("app.ingest") / "prompts" / "live_status.md").read_text(encoding="utf-8")
SEARCHES = {"search_public_sources"}
READS = {"read_page", "fetch_document", "read_document_pages", "read_library_document", "read_vault_document"}


class _Answer(BaseModel):
    answer: str
    kind: str


def run_state(messages: list[Any]) -> dict[str, Any]:
    """What the supervisor's checkpoint says: the request, the sources, the researchers and their returns."""
    asked = [m.text for m in messages if isinstance(m, HumanMessage)][-1:]
    launched = [c["args"].get("description", "")[:200] for m in messages if isinstance(m, AIMessage)
                for c in m.tool_calls if c["name"] == "task"]
    sources = next((str(m.content)[:600] for m in messages
                    if isinstance(m, ToolMessage) and m.name == "choose_sources"), None)
    returned = []
    for m in messages:
        if isinstance(m, ToolMessage) and m.name == "task" and isinstance(m.content, str):
            try:
                s = json.loads(m.content)
            except ValueError:
                continue
            if isinstance(s, dict):
                returned.append({k: s.get(k) for k in ("entity_name", "status", "fact_count", "not_found")})
    return {"asked": asked, "sources": sources, "launched": launched, "returned": returned}


def progress(body: AskLiveIn) -> dict[str, dict[str, Any]]:
    """Per researcher, from the Working board: searches, reads and whether it has saved."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"searches": 0, "reads": 0, "saved": False, "working": False})
    for step in body.steps:
        row = out[step.owner or "Scout"]
        row["searches"] += step.tool in SEARCHES
        row["reads"] += step.tool in READS
        row["saved"] |= step.tool == "save_research" and not step.running
        row["working"] |= step.running
    return dict(out)


async def saved_since(pool: AsyncConnectionPool, user_id: UUID, since: datetime | None) -> list[dict[str, Any]]:
    if since is None:
        return []
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT entity_name, entity_kind, status, fact_count FROM entity_research "
            "WHERE researched_at >= %s AND researched_by = %s ORDER BY researched_at",
            (since, user_id),
        )
        return list(await cur.fetchall())


async def answer(graph, pool: AsyncConnectionPool, thread_id: str, user_id: UUID, body: AskLiveIn,
                 settings: Settings) -> AskLiveOut:
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    state = {
        "run": run_state(snapshot.values.get("messages", [])),
        "saved": await saved_since(pool, user_id, body.since),
        "progress": progress(body),
    }
    model = resolve_model(settings.utility_model).with_structured_output(_Answer)
    reply = await model.ainvoke([
        SystemMessage(PROMPT),
        HumanMessage(f"State:\n{json.dumps(state, default=str)}\n\nQuestion: {body.question}"),
    ])
    kind = reply.kind if reply.kind in ("status", "instruction") else "status"
    return AskLiveOut(answer=reply.answer, kind=kind)
