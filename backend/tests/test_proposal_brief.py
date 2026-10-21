"""The research brief: one call with Anthropic's web search and fetch, resumed when it pauses, never raising."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.proposals import brief


class Model:
    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    async def ainvoke(self, messages):
        self.asked.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def said(*blocks, stop="end_turn"):
    return AIMessage(content=list(blocks), response_metadata={"stop_reason": stop})


def text(t):
    return {"type": "text", "text": t}


SEARCH = {"type": "server_tool_use", "name": "web_search", "id": "s1", "input": {"query": "NFHS-5 Assam"}}
RESULT = {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []}


def test_it_binds_web_search_and_fetch():
    class Bindable:
        def bind_tools(self, tools):
            return tools

    full, searching = brief.bind(Bindable())
    assert [t["type"] for t in full] == ["web_search_20250305", "web_fetch_20250910"]
    assert full[0]["max_uses"] == brief.SEARCHES and full[1]["max_uses"] == brief.FETCHES
    assert full[1]["max_content_tokens"] == brief.FETCHED and searching == full[:1]


async def test_only_the_text_after_the_last_search_is_the_brief():
    model = Model(said(text("Let me search."), SEARCH, RESULT, text("**A. Problem"), text(" magnitude**")))
    assert await brief.write("task", (model,)) == "**A. Problem magnitude**"
    assert model.asked[0][0].content == brief.PROMPT and model.asked[0][1].content == "task"


async def test_a_paused_turn_is_resumed_a_few_times_at_most():
    paused = said(text("Searching."), SEARCH, RESULT, text("Half"), stop="pause_turn")
    model = Model(paused, said(text(" done")))
    assert await brief.write("task", (model,)) == "Half done"
    assert model.asked[1][-1] is paused
    forever = Model(*[said(text("x"), stop="pause_turn") for _ in range(brief.TURNS + 1)])
    await brief.write("task", (forever,))
    assert len(forever.asked) == brief.TURNS


async def test_a_failure_or_nothing_written_is_no_brief():
    assert await brief.write("task", (Model(RuntimeError("401")),)) is None
    assert await brief.write("task", (Model(said(SEARCH, RESULT)),)) is None
    assert await brief.write("task", None) is None


async def test_the_brief_is_capped():
    assert len(await brief.write("task", (Model(said(text("x" * (brief.TEXT + 5)))),))) == brief.TEXT


async def test_a_call_to_a_tool_it_lacks_is_answered_and_it_carries_on():
    call = {"type": "tool_use", "name": "fetch", "id": "c1", "input": {"url": "https://niti.gov.in/mpi.pdf"}}
    asked = AIMessage(
        content=[text("Opening."), call],
        tool_calls=[{"name": "fetch", "args": call["input"], "id": "c1"}],
        response_metadata={"stop_reason": "tool_use"},
    )
    model = Model(asked, said(text("**A. Problem magnitude**")))
    assert await brief.write("task", (model,)) == "**A. Problem magnitude**"
    answer = model.asked[1][-1]
    assert answer.tool_call_id == "c1" and answer.status == "error" and answer.content == brief.NO_TOOL


async def test_a_brief_that_overflows_is_written_again_without_fetch():
    from langchain_core.exceptions import ContextOverflowError

    fetching, searching = Model(ContextOverflowError("prompt is too long")), Model(said(text("**A. Problem**")))
    assert await brief.write("task", (fetching, searching)) == "**A. Problem**"
    assert len(fetching.asked) == 1 and len(searching.asked) == 1
    assert await brief.write("task", (Model(ContextOverflowError("x")),)) is None
