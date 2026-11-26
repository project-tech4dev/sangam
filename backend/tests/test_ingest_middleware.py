"""Import's middleware: tier fallbacks, the researcher's budgets, escalation, the judge and summarizer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agentkit.middleware import SUMMARY_INPUT_TOKENS, SUMMARY_PROMPT, cheap_summarizer
from app.ingest import middleware as mw
from app.ingest.research import draft
from app.ingest.research.judge import ResearchJudge

TIERS = {"model": "m:strong", "research_model": "m:mid", "utility_model": "m:cheap"}


def of(stack, kind):
    return [m for m in stack if isinstance(m, kind)]


def fallbacks(stack) -> list[str]:
    return [model.name for m in of(stack, ModelFallbackMiddleware) for model in m.models]


@pytest.fixture
def built(build_import):
    seen = build_import(**TIERS)
    names = {"entity-researcher": "researcher", "catalog-writer": "writer", "workbook-reader": "reader",
             "vault-reader": "vault"}
    return SimpleNamespace(main=seen["middleware"], **{names[s["name"]]: s["middleware"] for s in seen["subagents"]})


class TestEachTierFallsBackToTheNext:
    def test_the_fallback_order_comes_from_the_tiers(self, built):
        assert fallbacks(built.main) == ["m:mid"]
        assert fallbacks(built.researcher) == ["m:strong"]
        assert fallbacks(built.writer) == ["m:mid"]
        assert fallbacks(built.reader) == ["m:mid"]
        assert fallbacks(built.vault) == ["m:strong"]

    def test_a_fallback_to_the_same_model_is_skipped(self, build_import):
        seen = build_import(model="m:strong", research_model="m:strong", utility_model="m:strong")
        stacks = [seen["middleware"], *(s["middleware"] for s in seen["subagents"])]
        assert all(not of(stack, ModelFallbackMiddleware) for stack in stacks)

    def test_utility_skips_a_research_tier_that_is_the_main_model(self, build_import):
        seen = build_import(model="m:strong", research_model="m:strong", utility_model="m:cheap")
        writer = next(s for s in seen["subagents"] if s["name"] == "catalog-writer")
        assert fallbacks(writer["middleware"]) == ["m:strong"]


class TestTheResearcherReadsToABudget:
    def test_the_limits_come_from_settings(self, build_import):
        seen = build_import(**TIERS, research_page_limit=5, research_model_call_limit=33)
        stack = next(s for s in seen["subagents"] if s["name"] == "entity-researcher")["middleware"]
        assert of(stack, mw.ReadingLimit)[0].limit == 5
        assert of(stack, ModelCallLimitMiddleware)[0].run_limit == 33

    def test_the_writer_has_a_call_limit_and_the_reader_none(self, built):
        assert of(built.writer, ModelCallLimitMiddleware)
        assert not of(built.reader, ModelCallLimitMiddleware)

    @staticmethod
    def request(call_id, calls, name="read_page"):
        state = {"messages": [HumanMessage("go"), AIMessage("", tool_calls=calls)]}
        return SimpleNamespace(tool_call={"name": name, "id": call_id, "args": {}}, state=state)

    def test_reads_past_the_limit_are_refused_in_order(self):
        limit = mw.ReadingLimit(2)
        calls = [{"name": t, "id": f"c{i}", "args": {}} for i, t in enumerate(["read_page", "fetch_document", "read_document_pages"])]
        ran = []
        for i, call in enumerate(calls):
            out = limit.wrap_tool_call(self.request(call["id"], calls, call["name"]), lambda r: ran.append(r) or "read")
            assert (out == "read") == (i < 2)
        refused = limit.wrap_tool_call(self.request("c2", calls, "read_document_pages"), lambda r: "read")
        # A message the model acts on, not an exception, carrying the phrase the board matches.
        assert isinstance(refused, ToolMessage) and mw.READING_LIMIT in refused.content
        assert refused.tool_call_id == "c2"

    def test_a_find_inside_a_document_spends_no_read(self):
        limit = mw.ReadingLimit(1)
        calls = [{"name": "read_document_pages", "id": "f", "args": {"filename": "ar.pdf", "find": "CSR"}},
                 {"name": "read_document_pages", "id": "r", "args": {"filename": "ar.pdf", "start_page": 211}}]

        def request(call):
            return SimpleNamespace(tool_call=call, state={"messages": [AIMessage("", tool_calls=calls)]})

        assert [limit.wrap_tool_call(request(c), lambda r: "read") for c in calls] == ["read", "read"]

    def test_other_tools_are_never_counted(self):
        limit = mw.ReadingLimit(0)
        calls = [{"name": "save_research", "id": "s", "args": {}}]
        assert limit.wrap_tool_call(self.request("s", calls, "save_research"), lambda r: "saved") == "saved"

    async def test_the_async_path_refuses_too(self):
        limit = mw.ReadingLimit(0)
        calls = [{"name": "read_page", "id": "c0", "args": {}}]

        async def handler(r):
            return "read"

        assert isinstance(await limit.awrap_tool_call(self.request("c0", calls), handler), ToolMessage)

    def test_the_researcher_evicts_long_results_sooner(self, built):
        from deepagents.middleware.filesystem import FilesystemMiddleware

        from app.ingest.agent import RESEARCHER_EVICT_AT

        assert of(built.researcher, FilesystemMiddleware)[0]._tool_token_limit_before_evict == RESEARCHER_EVICT_AT
        assert of(built.main, FilesystemMiddleware)[0]._tool_token_limit_before_evict == 20_000


class TestTwoContentRefusalsMoveTheRunToTheStrongModel:
    def request(self):
        return SimpleNamespace(messages=[HumanMessage("go")], override=lambda **kw: ("overridden", kw["model"]))

    def test_the_request_is_overridden_after_two_refusals_only(self):
        strong = object()
        escalate = mw.EscalateAfterFailedSave(strong)
        assert escalate.wrap_model_call(self.request(), lambda r: r).messages
        with draft.drafting() as current:
            current.refusals = 1
            assert escalate.wrap_model_call(self.request(), lambda r: r).messages
            current.refusals = 2
            assert escalate.wrap_model_call(self.request(), lambda r: r) == ("overridden", strong)

    def test_only_a_researcher_below_the_strong_tier_escalates(self, build_import):
        def researcher(**tiers):
            seen = build_import(**tiers)
            return next(s for s in seen["subagents"] if s["name"] == "entity-researcher")["middleware"]

        assert of(researcher(**TIERS), mw.EscalateAfterFailedSave)[0].strong.name == "m:strong"
        assert not of(researcher(model="m:strong", research_model="m:strong", utility_model="m:strong"), mw.EscalateAfterFailedSave)


class TestQualityIsJudgedNotGraded:
    LANGFUSE = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}

    def researcher(self, build_import, **over):
        seen = build_import(**TIERS, **over)
        return next(s for s in seen["subagents"] if s["name"] == "entity-researcher")["middleware"]

    def test_the_judge_runs_on_the_utility_tier_and_only_on_the_researcher(self, build_import):
        seen = build_import(**TIERS, **self.LANGFUSE)
        (judge,) = of(self.researcher(build_import, **self.LANGFUSE), ResearchJudge)
        assert judge.model.name == "m:cheap"
        assert not of(seen["middleware"], ResearchJudge)

    def test_off_or_no_langfuse_turns_it_off(self, build_import):
        assert not of(self.researcher(build_import, research_judge_model="off", **self.LANGFUSE), ResearchJudge)
        assert not of(self.researcher(build_import, langfuse_public_key="", langfuse_secret_key=""), ResearchJudge)

    def test_old_tool_results_are_cleared_on_the_researcher(self, built):
        (clearing,) = of(built.researcher, ContextEditingMiddleware)
        assert any(isinstance(e, ClearToolUsesEdit) for e in clearing.edits)


class TestSummariesAreWrittenByTheUtilityTier:
    def test_the_supervisor_and_researcher_summarize_on_utility_at_their_own_thresholds(self, built):
        from deepagents.middleware.summarization import SummarizationMiddleware

        for stack in (built.main, built.researcher):
            (summary,) = of(stack, SummarizationMiddleware)
            assert summary.model.name == "m:cheap"
            assert summary._lc_helper.trigger == ("tokens", 170000)
            assert summary._lc_helper.keep == ("tokens", 20000)
            assert summary._lc_helper.trim_tokens_to_summarize == SUMMARY_INPUT_TOKENS

    def test_a_1m_window_does_not_move_the_thresholds(self, tmp_path):
        # Sonnet 5.5's profile says 1M; read as 85% of it, the trigger was 850k.
        from deepagents.backends import FilesystemBackend
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        model = GenericFakeChatModel(messages=iter([]), profile={"max_input_tokens": 1_000_000})
        summary = cheap_summarizer(model, FilesystemBackend(root_dir=tmp_path))
        assert summary._lc_helper.trigger == ("tokens", 170000)
        assert summary._lc_helper.keep == ("tokens", 20000)
        assert summary._truncate_args_trigger == ("tokens", 170000)

    def test_the_summary_keeps_each_source_by_its_full_url(self, tmp_path):
        from deepagents.backends import FilesystemBackend
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        # If deepagents renames its </instructions> tag, the replace finds nothing and this fails.
        assert SUMMARY_PROMPT.count("## SOURCES") == 1
        assert SUMMARY_PROMPT.index("## SOURCES") < SUMMARY_PROMPT.index("</instructions>")
        summary = cheap_summarizer(GenericFakeChatModel(messages=iter([])), FilesystemBackend(root_dir=tmp_path))
        assert summary._lc_helper.summary_prompt == SUMMARY_PROMPT

    def test_ours_replaces_the_one_deepagents_adds(self, monkeypatch):
        # Every create_agent call deepagents makes, so the stacks it actually compiles can be checked.
        import deepagents.graph
        import deepagents.middleware.subagents
        from deepagents.middleware.summarization import SummarizationMiddleware

        from app.core.config import Settings
        from app.ingest.agent import build_ingest_agent

        stacks: dict[str, list] = {}
        real = deepagents.graph.create_agent

        def spy(model, **kwargs):
            stacks[kwargs.get("name") or "supervisor"] = kwargs["middleware"]
            return real(model, **kwargs)

        monkeypatch.setattr(deepagents.graph, "create_agent", spy)
        monkeypatch.setattr(deepagents.middleware.subagents, "create_agent", spy)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        build_ingest_agent(Settings(_env_file=None), None)
        settings = Settings(_env_file=None)
        for name in ("supervisor", "entity-researcher"):
            (summary,) = of(stacks[name], SummarizationMiddleware)
            assert summary.model.model == settings.utility_model.split(":", 1)[1], name


class TestANoteGoesAfterTheSystemMessage:
    def test_it_is_a_block_of_its_own(self):
        from langchain_core.messages import SystemMessage

        out = mw.append_to_system_message(SystemMessage("rules"), "note")
        assert [b["text"] for b in out.content_blocks] == ["rules", "\n\nnote"]
        assert mw.append_to_system_message(None, "note").content_blocks[0]["text"] == "note"


class TestTheCheckpointSizeIsScored:
    @pytest.fixture
    def scored(self, monkeypatch):
        from contextlib import asynccontextmanager

        sent, asked, waits = [], [], []

        class Pool:
            @asynccontextmanager
            async def connection(self, timeout=None):
                waits.append(timeout)
                yield object()

        async def size(conn, thread_id):
            asked.append(thread_id)
            return 3_204_000

        monkeypatch.setattr(mw, "get_config", lambda: {"configurable": {"thread_id": "import-1"}})
        monkeypatch.setattr(mw, "get_pool", Pool)
        monkeypatch.setattr(mw, "thread_bytes", size)
        monkeypatch.setattr(mw, "score_answer", lambda name, value: sent.append((name, value)))
        return SimpleNamespace(sent=sent, asked=asked, waits=waits)

    async def test_a_turn_sends_its_thread_size_once(self, scored):
        assert await mw.CheckpointSize().aafter_agent({"messages": []}, None) is None
        assert scored.asked == ["import-1"] and scored.sent == [("checkpoint_mb", 3.2)]
        # A short, bounded wait: the turn is not held for the pool's own timeout.
        assert scored.waits == [mw.CHECKPOINT_SIZE_WAIT_S]

    async def test_a_failed_query_sends_nothing_and_never_raises(self, scored, monkeypatch):
        async def broken(conn, thread_id):
            raise RuntimeError("pool closed")

        monkeypatch.setattr(mw, "thread_bytes", broken)
        await mw.CheckpointSize().aafter_agent({"messages": []}, None)
        assert scored.sent == []

    def test_only_scout_carries_it_and_only_with_langfuse(self, build_import):
        on = build_import(**TIERS, langfuse_public_key="pk", langfuse_secret_key="sk")
        off = build_import(**TIERS, langfuse_public_key="", langfuse_secret_key="")
        assert of(on["middleware"], mw.CheckpointSize) and not of(off["middleware"], mw.CheckpointSize)
        assert all(not of(s["middleware"], mw.CheckpointSize) for s in on["subagents"])
