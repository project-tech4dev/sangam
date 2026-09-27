"""Golden questions through the real agent.

    make evals                      every case
    make evals TAG=canary           the cheap subset
    pytest tests/evals --run-evals  directly

These cost money. Without --run-evals they skip.

Two cases are EXPECTED TO FAIL today, and both are data bugs rather than agent
bugs — see their `note`. Do not try to fix them with prompt engineering; they
pass when the schema migrations land, and until then they are the regression
test proving the agent discloses the problem instead of reporting it as truth.
"""

from __future__ import annotations

import psycopg_pool
import pytest
from psycopg.rows import dict_row

import app.db.pool as db_pool
from tests.evals.conftest import DSN, load_cases
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
            # strict: when the underlying data is fixed the case starts passing,
            # pytest reports XPASS as a failure, and someone deletes the marker.
            # A permanently-red suite gets ignored; a suite that goes red when a
            # bug is FIXED gets read.
            marks.append(pytest.mark.xfail(reason=case["expected_failure"], strict=True))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    metafunc.parametrize("case", params)


@pytest.fixture
async def agent_pool():
    """The agent's tools reach the database through the module-level pool, the
    same way they do in the app — there is no per-request injection for them.

    Function-scoped on purpose. A module-scoped async fixture is created on a
    different event loop than the tests that use it, and an AsyncConnectionPool
    bound to a dead loop fails every checkout — which surfaces as the agent
    politely reporting "the database is unreachable" and every case failing for
    a reason that has nothing to do with the agent.
    """
    pool = psycopg_pool.AsyncConnectionPool(
        DSN,
        min_size=1,
        max_size=3,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    db_pool.pool = pool
    try:
        yield pool
    finally:
        await pool.close()
        db_pool.pool = None


def _best_match(db, statements, gold_rows, answer, result):
    """The agent result that satisfies the gold, or the last one for reporting."""
    from tests.evals.sql_compare import gold_satisfied

    executed = []
    for sql in statements:
        try:
            rows = [tuple(r.values()) for r in db.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001 - a broken agent query is a finding
            result.failures.append(f"the agent's SQL does not re-run: {exc}")
            continue
        executed.append(rows)
        if gold_satisfied(gold_rows, rows, answer):
            return rows
    return executed[-1] if executed else []


async def test_case(case, eval_settings, slug_ids, db, agent_pool):
    resolved = dict(case)
    for key in ("required_citations", "forbidden_citations"):
        resolved[key] = [slug_ids.get(m, m) for m in case.get(key, [])]

    try:
        answer, agent_sql, citations = await run_agent(case["question"], eval_settings)
    except TimeoutError:
        pytest.fail(
            f"[{case['id']}] timed out after {CASE_TIMEOUT_SECONDS}s — either the model "
            "request hung or the agent is looping",
            pytrace=False,
        )
    result = CaseResult(case_id=case["id"], answer=answer, agent_sql=agent_sql, citations=citations)

    gold_rows, agent_rows = None, None
    if case.get("gold_sql"):
        gold_rows = [tuple(r.values()) for r in db.execute(case["gold_sql"]).fetchall()]
        if agent_sql:
            # Every query the agent ran, not just the last one. Agents work in
            # steps — asked for the top fit score, one ran the ranking query and
            # then a follow-up for the adjustment log, and scoring the LAST query
            # compared the gold against the adjustment rows and failed a correct
            # answer. Any query satisfying the gold means it retrieved the data.
            agent_rows = _best_match(db, agent_sql, gold_rows, answer, result)

    score(resolved, result, gold_rows=gold_rows, agent_rows=agent_rows)

    if not result.passed:
        report = [f"[{case['id']}] {case['question']}", ""]
        report += [f"  FAIL: {f}" for f in result.failures]
        report.append("")
        for sql in agent_sql:
            report.append(f"  agent sql : {sql[:220]}")
        report.append(f"  citations : {sorted(citations) or 'none'}")
        report.append(f"  answer    : {answer[:600]}")
        if case.get("note"):
            report += ["", f"  NOTE: {case['note']}"]
        pytest.fail("\n".join(report), pytrace=False)
