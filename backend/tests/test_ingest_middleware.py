"""Import's middleware: tier fallbacks, the researcher's budgets, escalation, rubric and summarizer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ingest import middleware as mw

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


def save_result(content, status="success"):
    return ToolMessage(content, tool_call_id="s", name="save_research", status=status)


class TestAFailedSaveMovesToTheStrongModel:
    @pytest.mark.parametrize(
        ("message", "failed"),
        [
            (save_result("Error invoking tool 'save_research' with kwargs {} with error: ...", "error"), True),
            (save_result("anything", "error"), True),
            (save_result("Saved as entity_research #4 (kabil): 3 findings"), False),
            # A refusal is the tool working: the strong model would get the same answer.
            (save_result("REFUSED: kabil already has 9 findings saved today"), False),
            # The database failing is not the payload's fault.
            (save_result("save_research failed: OperationalError. Report your findings in text."), False),
            (ToolMessage("Error invoking tool", tool_call_id="r", name="read_page", status="error"), False),
        ],
    )
    def test_which_results_count_as_a_failed_save(self, message, failed):
        assert mw.save_failed([HumanMessage("go"), message]) is failed

    def test_the_request_is_overridden_after_a_failure_only(self):
        strong = object()
        escalate = mw.EscalateAfterFailedSave(strong)

        def request(messages):
            return SimpleNamespace(messages=messages, override=lambda **kw: ("overridden", kw["model"]))

        assert escalate.wrap_model_call(request([HumanMessage("go")]), lambda r: r).messages
        failed = request([save_result("bad", "error")])
        assert escalate.wrap_model_call(failed, lambda r: r) == ("overridden", strong)

    def test_only_a_researcher_below_the_strong_tier_escalates(self, build_import):
        def researcher(**tiers):
            seen = build_import(**tiers)
            return next(s for s in seen["subagents"] if s["name"] == "entity-researcher")["middleware"]

        assert of(researcher(**TIERS), mw.EscalateAfterFailedSave)[0].strong.name == "m:strong"
        assert not of(researcher(model="m:strong", research_model="m:strong", utility_model="m:strong"), mw.EscalateAfterFailedSave)


class TestTheRubricGradesTheResearcher:
    def test_the_grader_runs_on_the_utility_tier(self, built):
        (rubric,) = of(built.researcher, mw.ResearchRubric)
        assert rubric._model.name == "m:cheap" and rubric.max_iterations == 2
        assert not of(built.writer, mw.ResearchRubric) and not of(built.main, mw.ResearchRubric)

    def test_the_rubric_starts_a_grading_run_without_entering_state(self):
        # A public `rubric` key in the update would flow back to the parent through the task tool.
        update = mw.research_rubric(object()).before_agent({"messages": []}, None)
        assert update["_active_rubric"] == mw.RUBRIC and update["_rubric_iterations"] == 0
        assert "rubric" not in update

    def test_a_revision_can_jump_back_to_the_model(self, monkeypatch):
        # Without the edge, needs_revision is graded and then ignored.
        from app.core.config import Settings
        from app.ingest.agent import build_ingest_agent

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        task = build_ingest_agent(Settings(_env_file=None), None).nodes["tools"].bound.tools_by_name["task"]
        graphs = next(c.cell_contents for c in (task.func or task.coroutine).__closure__
                      if isinstance(c.cell_contents, dict) and "entity-researcher" in c.cell_contents)
        edges = {(e.source, e.target) for e in graphs["entity-researcher"].get_graph().edges}
        # "model" enters through the before_model hooks, so a revision still counts against the call limit.
        assert ("ResearchRubric.after_agent", "ModelCallLimitMiddleware.before_model") in edges

    def test_a_save_reaches_the_grader_as_a_digest(self):
        findings = [{"concept": "csr_year", "evidence": "x" * 5000}, {"concept": "rfp", "evidence": "y"}]
        save = {
            "name": "save_research",
            "id": "s",
            "args": {"findings": {"status": "partial", "goals": ["csr_year", "rfp", "geography"], "findings": findings,
                                  "gaps": [{"concept": "geography", "reason": "blocked", "detail": "site.org 403"}]}},
        }
        other = {"name": "read_page", "id": "r", "args": {"url": "https://a.org"}}
        out = mw.digest_saves([HumanMessage("go"), AIMessage("saving", tool_calls=[other, save])])
        args = {c["name"]: c["args"] for c in out[1].tool_calls}
        assert args["read_page"] == {"url": "https://a.org"}
        assert args["save_research"]["finding_count"] == 2
        assert args["save_research"]["concepts_found"] == ["csr_year", "rfp"]
        assert args["save_research"]["gaps"][0]["reason"] == "blocked"
        assert "xxxx" not in str(out)


class TestSummariesAreWrittenByTheUtilityTier:
    def test_the_supervisor_and_researcher_summarize_on_utility_at_their_own_thresholds(self, built):
        from deepagents.middleware.summarization import SummarizationMiddleware

        for stack in (built.main, built.researcher):
            (summary,) = of(stack, SummarizationMiddleware)
            assert summary.model.name == "m:cheap"
            # The fakes have no profile, as Opus 5.5 and Sonnet 5.5 have none: the fixed thresholds stand.
            assert summary._lc_helper.trigger == ("tokens", 170000)
            assert summary._lc_helper.trim_tokens_to_summarize == mw.SUMMARY_INPUT_TOKENS

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
