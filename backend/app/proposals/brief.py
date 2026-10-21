"""Secondary research's brief: one model call with Anthropic's own web search and fetch, the way a person would ask.

The brief only cites; it never reaches the proposal text. So it runs outside `check_url` (the registry and robots.txt
gate the fact list's reader keeps), and Anthropic's fetcher follows robots.txt itself. Its task never names the
organisation: server-side search cannot be filtered by `PublicGuard`, so the name is simply never given.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "research_brief.md").read_text(encoding="utf-8")
SEARCHES, FETCHES = 20, 8
FETCHED = 15000  # tokens kept of one fetched page: a whole NFHS report would overflow the context
TURNS = 4  # a long search pauses the turn, or the model calls a tool it doesn't have; resumed this many times at most
NO_TOOL = "There is no such tool. Open pages with web_fetch, or write the brief now."
TEXT = 20000
TOOLS = [
    {"type": "web_search_20250305", "name": "web_search", "max_uses": SEARCHES},
    {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": FETCHES, "max_content_tokens": FETCHED},
]


def bind(model: Any) -> Any:
    return model.bind_tools(TOOLS)


def _after_tools(message: BaseMessage, kept: str) -> str:
    """The text written after the last search or fetch: the brief, without the "let me search…" lines before it."""
    content = message.content
    if isinstance(content, str):
        return kept + content
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            kept += block.get("text", "")
        else:  # server_tool_use or a search/fetch result: what came before it was working notes
            kept = ""
    return kept


async def write(task: str, model: Any) -> str | None:
    """The brief in Markdown, or None when the call failed or wrote nothing; never raises."""
    if model is None:
        return None
    messages: list[BaseMessage] = [SystemMessage(PROMPT), HumanMessage(task)]
    text = ""
    try:
        for _ in range(TURNS):
            reply: AIMessage = await model.ainvoke(messages)
            text = _after_tools(reply, text)
            stop = (reply.response_metadata or {}).get("stop_reason")
            if stop not in ("pause_turn", "tool_use"):
                break
            messages.append(reply)
            # Only server tools are bound, so a client tool call names one that doesn't exist (seen: "fetch").
            messages += [
                ToolMessage(NO_TOOL, tool_call_id=call["id"], status="error") for call in reply.tool_calls
            ]
    except Exception as exc:  # noqa: BLE001 - a failed brief never fails the search
        logger.warning(f"[write] research brief failed ({type(exc).__name__})")
        return None
    return text.strip()[:TEXT] or None
