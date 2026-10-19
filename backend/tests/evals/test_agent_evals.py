"""Golden questions through the real agent."""

from __future__ import annotations

import pathlib
import time
from typing import Any

import psycopg_pool
import pytest
from psycopg.rows import dict_row

import app.db.pool as db_pool
from tests.evals.conftest import DSN, SUMMARY_KEY, load_cases, read_only
from tests.evals.experiment import run_cases
from tests.evals.harness import CASE_TIMEOUT_SECONDS, CaseResult, run_agent, score

pytestmark = pytest.mark.eval


def pytest_generate_tests(metafunc):
    if "case" not in metafunc.fixturenames:
        return
    tag = metafunc.config.getoption("--eval-tag")
    cases = load_cases(tag)
    params = []
    for case in cases:
        marks = []
        if case.get("expected_failure"):
            # strict: fixing the data makes the case pass, XPASS fails the suite, and the
            # marker gets deleted. A permanently-red suite gets ignored.
            marks.append(pytest.mark.xfail(reason=case["expected_failure"], strict=True))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    metafunc.parametrize("case", params)


def _best_match(db, statements, gold_rows, answer, result):
    """The agent result that satisfies the gold, or the last one for reporting."""
    from tests.evals.sql_compare import agent_values, gold_satisfied

    executed = []
    for sql in statements:
        try:
            rows = [agent_values(r) for r in db.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001 - a broken agent query is a finding
            result.failures.append(f"the agent's SQL does not re-run: {exc}")
            continue
        executed.append(rows)
        if gold_satisfied(gold_rows, rows, answer):
            return rows
    return executed[-1] if executed else []


def _make_task(eval_settings, slug_ids, db):
    async def task(case: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(case)
        for key in ("required_citations", "forbidden_citations"):
            resolved[key] = [slug_ids.get(m, m) for m in case.get(key, [])]

        # A cost case runs long before its fix, and a timeout would lose the very numbers it measures.
        timeout = case.get("timeout_seconds", CASE_TIMEOUT_SECONDS)
        # Opened per case, inside the loop that runs it: Langfuse may run the experiment on its own loop.
        pool = psycopg_pool.AsyncConnectionPool(
            DSN,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            configure=read_only,
        )
        await pool.open()
        db_pool.pool = pool
        started = time.monotonic()
        try:
            run = await run_agent(case["question"], eval_settings, timeout=timeout)
        except TimeoutError:
            return {"failures": [f"timed out after {timeout}s: the model hung or the agent looped"]}
        except Exception as exc:  # noqa: BLE001 - one broken case must not lose the rest of the run
            return {"failures": [f"the agent raised {type(exc).__name__}: {exc}"]}
        finally:
            await pool.close()
            db_pool.pool = None

        result = CaseResult(
            case_id=case["id"], answer=run.answer, agent_sql=run.agent_sql, citations=run.citations, stats=run.stats
        )
        gold_rows, agent_rows = None, None
        if case.get("gold_sql"):
            gold_rows = [tuple(r.values()) for r in db.execute(case["gold_sql"]).fetchall()]
            if run.agent_sql:
                # Every query the agent ran, not just the last: agents work in steps, and
                # scoring only the final one failed a correct answer.
                agent_rows = _best_match(db, run.agent_sql, gold_rows, run.answer, result)
        result.stats.seconds = round(time.monotonic() - started, 1)
        score(resolved, result, gold_rows=gold_rows, agent_rows=agent_rows)
        return {
            "answer": run.answer,
            "agent_sql": run.agent_sql,
            "citations": sorted(run.citations),
            "failures": result.failures,
            "warnings": result.warnings,
            "stats": run.stats.as_dict(),
        }

    return task


@pytest.fixture(scope="session")
def outputs(request, eval_settings, slug_ids, db) -> dict[str, dict]:
    """Every selected case, run once: through a Langfuse experiment when tracing is on."""
    # Only what pytest selected (-k, --eval-tag, a node id), so a narrowed run bills only those cases.
    here = pathlib.Path(__file__).name
    params = [getattr(getattr(i, "callspec", None), "params", {}) for i in request.session.items if i.path.name == here]
    cases = [p["case"] for p in params if "case" in p]
    results, url = run_cases(cases, _make_task(eval_settings, slug_ids, db), traced=eval_settings.langfuse_enabled)
    request.config.stash[SUMMARY_KEY] = (results, url)
    return results


def test_case(case, outputs):
    output = outputs.get(case["id"])
    if output is None:
        pytest.fail(f"[{case['id']}] produced no output; see the Langfuse run for the error", pytrace=False)
    if not output["failures"]:
        return
    report = [f"[{case['id']}] {case['question']}", ""]
    report += [f"  FAIL: {f}" for f in output["failures"]]
    report.append("")
    for sql in output.get("agent_sql", []):
        report.append(f"  agent sql : {sql[:220]}")
    report.append(f"  citations : {output.get('citations') or 'none'}")
    report.append(f"  answer    : {output.get('answer', '')[:600]}")
    if case.get("note"):
        report += ["", f"  NOTE: {case['note']}"]
    pytest.fail("\n".join(report), pytrace=False)
