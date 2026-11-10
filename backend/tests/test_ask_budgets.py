"""Ask's limits in code: a model-call cap per question, compare_fit budget, a fallback and a cheap summarizer."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import middleware as mw


def _fit(i: int, org_id: int = 8, funder_ids: list[int] | None = None) -> AIMessage:
    args = {"org_id": org_id, **({"funder_ids": funder_ids} if funder_ids is not None else {})}
    return AIMessage("", tool_calls=[{"name": "compare_fit", "args": args, "id": f"f{i}"}])


class TestCompareFitBudget:
    def test_the_first_call_runs(self):
        assert mw.compare_fit_refusal([HumanMessage("q"), _fit(1)], {"id": "f1"}) is None

    def test_the_same_arguments_again_are_refused(self):
        messages = [HumanMessage("q"), _fit(1), ToolMessage("ok", tool_call_id="f1", name="compare_fit"), _fit(2)]
        assert "repeat" in mw.compare_fit_refusal(messages, {"id": "f2"})

    def test_weak_funders_in_full_are_a_different_call(self):
        # compare_fit's own description: call compare_fit(org_id, [their ids]) once for any you need in full.
        messages = [HumanMessage("q"), _fit(1), _fit(2, funder_ids=[5, 3])]
        assert mw.compare_fit_refusal(messages, {"id": "f2"}) is None
        assert "repeat" in mw.compare_fit_refusal([*messages, _fit(3, funder_ids=[3, 5])], {"id": "f3"})

    def test_a_fourth_call_is_refused(self):
        messages = [HumanMessage("q"), _fit(1, 1), _fit(2, 2), _fit(3, 3), _fit(4, 4)]
        assert mw.compare_fit_refusal(messages, {"id": "f3"}) is None
        assert "3 calls" in mw.compare_fit_refusal(messages, {"id": "f4"})

    def test_a_new_question_starts_again(self):
        messages = [HumanMessage("q1"), _fit(1), HumanMessage("q2, same org"), _fit(2)]
        assert mw.compare_fit_refusal(messages, {"id": "f2"}) is None


class TestModelCallCap:
    def test_it_ends_the_turn_at_the_cap(self):
        cap = mw.model_call_cap(3)
        turn = [HumanMessage("old"), *[AIMessage("x")] * 5, HumanMessage("q"), AIMessage("a"), AIMessage("b")]
        assert cap.before_model({"messages": turn}, None) is None
        update = cap.before_model({"messages": [*turn, AIMessage("c")]}, None)
        assert update["jump_to"] == "end"
        assert update["messages"][0].content == mw._CAPPED


def _stack(monkeypatch, **env):
    import deepagents.graph

    from app.agent.build import build_agent
    from app.core.config import Settings

    seen: list = []
    real = deepagents.graph.create_agent

    def spy(model, **kwargs):
        seen.append(kwargs["middleware"])
        return real(model, **kwargs)

    monkeypatch.setattr(deepagents.graph, "create_agent", spy)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    graph = build_agent(Settings(_env_file=None), None)
    return seen[0], graph


def test_ask_falls_back_and_summarizes_on_the_cheap_tier(monkeypatch):
    from deepagents.middleware.summarization import SummarizationMiddleware
    from langchain.agents.middleware import ModelFallbackMiddleware

    from app.core.config import Settings

    stack, graph = _stack(monkeypatch)
    settings = Settings(_env_file=None)
    (fb,) = [m for m in stack if isinstance(m, ModelFallbackMiddleware)]
    assert fb.models[0].model == settings.research_model.split(":", 1)[1]
    (summary,) = [m for m in stack if isinstance(m, SummarizationMiddleware)]
    assert summary.model.model == settings.utility_model.split(":", 1)[1]
    assert any(isinstance(m, mw.CompareFitBudget) for m in stack)
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    # "end" leaves through the after_agent hooks (the audit), so the cap reaches one of them or __end__.
    exits = {t for src, t in edges if src == "ModelCallCap.before_model"}
    assert any(t == "__end__" or t.endswith(".after_agent") for t in exits)


def test_no_fallback_when_both_tiers_are_one_model(monkeypatch):
    from langchain.agents.middleware import ModelFallbackMiddleware

    stack, _ = _stack(monkeypatch, MODEL="anthropic:claude-sonnet-5-5", RESEARCH_MODEL="anthropic:claude-sonnet-5-5")
    assert not [m for m in stack if isinstance(m, ModelFallbackMiddleware)]
