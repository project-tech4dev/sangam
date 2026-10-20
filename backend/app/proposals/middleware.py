"""Tells the proposal agent where the proposal stands on every model call."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from langchain.agents.middleware import AgentMiddleware, ModelRequest, before_model
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.ingest.access import canonical_url
from app.ingest.middleware import _AgUiState
from app.integrations.storage import _safe_name
from app.proposals import context
from app.proposals import facts as fact_rules


def with_blocks(system: SystemMessage | None, stable: str, live: str, cache: bool) -> SystemMessage:
    """The stable block ends on a cache breakpoint (Anthropic only); the live block after it changes freely."""
    blocks: list[Any] = list(system.content_blocks) if system else []
    marked: dict[str, Any] = {"type": "text", "text": stable}
    if cache:
        marked["cache_control"] = {"type": "ephemeral"}
    return SystemMessage(content_blocks=[*blocks, marked, {"type": "text", "text": live}])


def with_screen(messages: list[Any], line: str) -> list[Any]:
    """The screen on the person's latest message too: their own earlier turns outweigh the system prompt."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, HumanMessage):
            note = {"type": "text", "text": f"({line})"}
            blocks = [{"type": "text", "text": m.content}] if isinstance(m.content, str) else list(m.content)
            return [*messages[:i], m.model_copy(update={"content": [*blocks, note]}), *messages[i + 1:]]
    return messages


class ProposalContext(AgentMiddleware):
    """Reads the proposal fresh each call: a save on screen between two calls is seen by the second."""

    state_schema = _AgUiState

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        p = await context.current()
        if p is None:
            return await handler(request)
        system = with_blocks(request.system_message, context.stable(p), context.live(p, request.state),
                             isinstance(request.model, ChatAnthropic))
        return await handler(request.override(system_message=system,
                                              messages=with_screen(request.messages, context.on_screen(p, request.state))))


@dataclass
class PublicRun:
    """One public research run: the names it may not search for, and the text of every page it read."""

    avoid: tuple[str, ...]
    pages: dict[str, str] = field(default_factory=dict)
    unopened: set[str] = field(default_factory=set)  # hosts a read was refused or failed on, shown on screen
    files: dict[str, str] = field(default_factory=dict)  # a fetched PDF's name → the url it came from


PUBLIC_RUN: ContextVar[PublicRun | None] = ContextVar("proposal_public_run", default=None)
_SAVED = re.compile(r"^Saved (\S+) \(")


def page_key(url: Any) -> str:
    """One key for one page however it is cited: no scheme, no "www.", no trailing slash."""
    try:
        text = canonical_url(str(url or "").strip())
    except Exception:  # noqa: BLE001 - a malformed url is simply not a page that was read
        text = str(url or "").strip()
    return re.sub(r"^https?://(www\.)?", "", text).rstrip("/").lower()


class PublicGuard(AgentMiddleware):
    """Refuses a search naming the org, and keeps each page's text so add_facts can find the quote on it."""

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        run = PUBLIC_RUN.get()
        call = request.tool_call
        name, args = call.get("name") or "", call.get("args") or {}
        if run is not None and name == "search_public_sources":
            query = fact_rules.norm(args.get("query"))
            if named := next((n for n in run.avoid if re.search(rf"\b{re.escape(fact_rules.norm(n))}\b", query)),
                             None):
                return ToolMessage(f"REFUSED: never search for {named}; search for the place and the problem.",
                                   tool_call_id=call.get("id"), name=name, status="error")
        result = await handler(request)
        if run is not None and isinstance(result, ToolMessage) and isinstance(result.content, str):
            text = result.content
            if name in ("read_page", "fetch_document") and text.startswith(("REFUSED", "ERROR", f"{name} failed")):
                if host := urlparse(str(args.get("url") or "")).hostname:
                    run.unopened.add(host)
            elif name == "read_page":
                run.pages[page_key(args.get("url"))] = text
            elif name == "fetch_document" and (m := _SAVED.match(text)):
                run.files[m.group(1)] = page_key(args.get("url"))
            elif name == "read_document_pages" and (url := run.files.get(_safe_name(str(args.get("filename") or "")))):
                run.pages[url] = run.pages.get(url, "") + "\n" + text
        return result


@before_model(can_jump_to=["end"], name="NothingToAnswer")
def nothing_to_answer(state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
    """A run with no new message would ask the model to continue its own reply, which Claude refuses with a 400."""
    messages = state["messages"]
    if not messages or (isinstance(messages[-1], AIMessage) and not messages[-1].tool_calls):
        return {"jump_to": "end"}
    return None
