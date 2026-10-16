"""The eval harness's cost counting and budgets, on recorded messages: no model, no database."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tests.evals import experiment
from tests.evals.harness import CaseResult, run_stats, score


def _ai(calls=(), *, inp=1000, out=100, cache_read=0, cache_creation=0, text=""):
    return AIMessage(
        content=text,
        tool_calls=[{"name": n, "args": a, "id": f"c{i}"} for i, (n, a) in enumerate(calls)],
        usage_metadata={
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "input_token_details": {"cache_read": cache_read, "cache_creation": cache_creation},
        },
    )


# The shape of trace 5bfdbc85: compare_fit evicted, read back, called again.
MESSAGES = [
    HumanMessage("What does Better Life Foundation do?"),
    _ai([("db_query", {"sql": "SELECT 1"})], cache_creation=7000),
    ToolMessage("columns: n", tool_call_id="c0", name="db_query"),
    _ai([("compare_fit", {"org_id": 8})], cache_read=7000),
    ToolMessage("Tool result too large", tool_call_id="c0", name="compare_fit"),
    _ai([("read_file", {"file_path": "/large_tool_results/abc"}), ("read_file", {"file_path": "/skills/x.md"})]),
    _ai([("compare_fit", {"org_id": 8})]),
    _ai(text="Better Life Foundation [org:8] …", out=400),
]


def test_counts_calls_tokens_and_large_result_reads():
    stats = run_stats(MESSAGES)
    assert stats.tool_calls == {"db_query": 1, "compare_fit": 2, "read_file": 2}
    assert stats.total_tool_calls == 5
    assert stats.model_calls == 5
    assert stats.input_tokens == 5000
    assert stats.output_tokens == 800
    assert (stats.cache_read_tokens, stats.cache_creation_tokens) == (7000, 7000)
    # Only the /large_tool_results read counts; reading a skill is normal.
    assert stats.large_result_reads == 1


def test_a_message_without_usage_is_not_a_model_call():
    stats = run_stats([AIMessage(content="cached replay")])
    assert stats.model_calls == 0 and stats.input_tokens == 0


def _scored(case):
    result = CaseResult(case_id="blf", stats=run_stats(MESSAGES))
    return score(case, result, gold_rows=None, agent_rows=None).failures


def test_call_budget_and_large_result_reads_fail_the_case():
    failures = _scored({"max_calls": {"compare_fit": 1}, "max_large_result_reads": 0})
    assert any("compare_fit 2 times; the budget is 1" in f for f in failures)
    assert any("/large_tool_results 1 times" in f for f in failures)


def test_within_budget_passes():
    assert _scored({"max_calls": {"compare_fit": 2, "db_query": 3}, "max_large_result_reads": 1}) == []


def test_evaluations_report_pass_counts_and_per_tool_calls():
    out = {"failures": [], "stats": run_stats(MESSAGES).as_dict()}
    scores = {e.name: e.value for e in experiment.evaluations(out)}
    assert scores["passed"] is True
    assert scores["total_tool_calls"] == 5
    assert scores["calls.compare_fit"] == 2
    assert scores["large_result_reads"] == 1


def test_a_failed_case_scores_passed_false_with_the_reasons():
    passed = next(e for e in experiment.evaluations({"failures": ["a", "b"], "stats": {}}) if e.name == "passed")
    assert passed.value is False and passed.comment == "a\nb"
    assert experiment.evaluations(None)[0].value is False


class _FakeLangfuse:
    def __init__(self, exists):
        self.exists, self.created, self.items = exists, [], []

    def get_dataset(self, name, **_):
        if not self.exists:
            raise LookupError(name)

    def create_dataset(self, **kw):
        self.created.append(kw["name"])

    def create_dataset_item(self, **kw):
        self.items.append(kw)


def test_sync_creates_the_dataset_once_and_upserts_items_by_case_id():
    case = {"id": "org-count", "question": "How many?", "tags": ["canary"]}
    fresh, existing = _FakeLangfuse(exists=False), _FakeLangfuse(exists=True)
    experiment.sync_dataset(fresh, [case])
    experiment.sync_dataset(existing, [case])
    assert fresh.created == ["ask-golden"] and existing.created == []
    item = existing.items[0]
    assert item["id"] == "ask:org-count"
    assert item["input"] == {"question": "How many?"}
    assert item["metadata"] == case


def test_untraced_run_loops_over_every_case():
    async def task(case):
        return {"failures": [], "seen": case["id"]}

    outputs, url = experiment.run_cases([{"id": "a"}, {"id": "b"}], task, traced=False)
    assert url is None
    assert {k: v["seen"] for k, v in outputs.items()} == {"a": "a", "b": "b"}
