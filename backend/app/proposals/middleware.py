"""Tells the proposal agent where the proposal stands on every model call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.ingest.middleware import _AgUiState
from app.proposals import context


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
