"""Run golden cases as a Langfuse dataset experiment, or as a plain loop when Langfuse is off."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any

DATASET = "ask-golden"
# Dataset item ids are unique across the whole Langfuse project, not per dataset.
ITEM_PREFIX = "ask:"
# The agent's tools share one module-level pool, so cases run one at a time.
MAX_CONCURRENCY = 1

# Scores posted on every item: numbers to compare across runs, never gates on their own.
NUMERIC_SCORES = (
    "total_tool_calls",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "large_result_reads",
)

Task = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def item_id(case: dict[str, Any]) -> str:
    return f"{ITEM_PREFIX}{case['id']}"


def run_name() -> str:
    """branch-sha, so a run names the code it measured."""
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    return "-".join(p for p in (git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "--short", "HEAD")) if p) or "local"


def evaluations(output: dict[str, Any] | None) -> list[Any]:
    from langfuse import Evaluation

    if not output:
        return [Evaluation(name="passed", value=False, comment="the task returned nothing")]
    failures = output.get("failures", [])
    stats = output.get("stats", {})
    scores = [Evaluation(name="passed", value=not failures, comment="\n".join(failures) or None)]
    scores += [Evaluation(name=name, value=stats.get(name, 0)) for name in NUMERIC_SCORES]
    scores += [
        Evaluation(name=f"calls.{tool}", value=n) for tool, n in sorted(stats.get("tool_calls", {}).items())
    ]
    return scores


def _item_evaluator(*, output: Any, **_: Any) -> list[Any]:
    return evaluations(output)


def _pass_rate(*, item_results: list[Any], **_: Any) -> Any:
    from langfuse import Evaluation

    passed = sum(1 for r in item_results if r.output and not r.output.get("failures"))
    return Evaluation(name="pass_rate", value=passed / len(item_results) if item_results else 0.0)


def sync_dataset(client: Any, cases: list[dict[str, Any]]) -> None:
    """golden.jsonl stays the source of truth; the dataset is a copy, upserted by id."""
    try:
        client.get_dataset(DATASET, fetch_items_page_size=1)
    except Exception:  # noqa: BLE001 - not found is the expected first-run case
        client.create_dataset(name=DATASET, description="Ask Sangam golden questions (tests/evals/cases)")
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET, id=item_id(case), input={"question": case["question"]}, metadata=case
        )


def run_cases(cases: list[dict[str, Any]], task: Task, *, traced: bool) -> tuple[dict[str, dict], str | None]:
    """{case id: task output}, and the Langfuse run's URL when there is one."""
    if not traced:
        async def loop() -> dict[str, dict]:
            return {case["id"]: await task(case) for case in cases}

        return asyncio.run(loop()), None

    from langfuse import get_client

    client = get_client()
    sync_dataset(client, cases)
    wanted = {item_id(c): c for c in cases}
    items = [i for i in client.get_dataset(DATASET).items if i.id in wanted]

    async def item_task(*, item: Any, **_: Any) -> dict[str, Any]:
        return await task(wanted[item.id])

    result = client.run_experiment(
        name=DATASET,
        run_name=run_name(),
        data=items,
        task=item_task,
        evaluators=[_item_evaluator],
        run_evaluators=[_pass_rate],
        max_concurrency=MAX_CONCURRENCY,
    )
    client.flush()
    outputs = {wanted[r.item.id]["id"]: r.output for r in result.item_results if r.output}
    return outputs, result.dataset_run_url
