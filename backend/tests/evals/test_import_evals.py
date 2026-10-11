"""Import canaries: one funder and one NGO through the real Import agent, judged on the row it saved."""

from __future__ import annotations

import json
import os
import pathlib
from datetime import UTC, datetime

import psycopg_pool
import pytest
from psycopg.rows import dict_row

import app.db.pool as db_pool
from tests.evals.conftest import DSN
from tests.evals.import_harness import IMPORT_CASE_TIMEOUT_SECONDS, run_import

pytestmark = pytest.mark.eval

CASES = pathlib.Path(__file__).parent / "cases" / "import"
TAGGED = {"program", "identity", "org_identity"}


def pytest_generate_tests(metafunc):
    if "import_case" not in metafunc.fixturenames:
        return
    tag = metafunc.config.getoption("--eval-tag")
    cases = [json.loads(line) for p in sorted(CASES.glob("*.jsonl")) for line in p.read_text().splitlines()
             if line.strip()]
    cases = [c for c in cases if not tag or tag in c.get("tags", [])]
    metafunc.parametrize("import_case", [pytest.param(c, id=c["id"]) for c in cases])


@pytest.fixture
async def import_pool():
    # Researchers run in parallel and each one reads and saves, so more room than an Ask question needs.
    pool = psycopg_pool.AsyncConnectionPool(
        DSN, min_size=1, max_size=6, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    db_pool.pool = pool
    try:
        yield pool
    finally:
        await pool.close()
        db_pool.pool = None


async def test_import_case(import_case, eval_settings, db, import_pool):
    if not os.environ.get("TAVILY_API_KEY") and not eval_settings.tavily_api_key:
        pytest.skip("TAVILY_API_KEY is not set, so search_public_sources has nothing to search")
    case = import_case
    started = datetime.now(UTC)
    try:
        summaries = await run_import(case["request"], eval_settings)
    except TimeoutError:
        pytest.fail(f"[{case['id']}] timed out after {IMPORT_CASE_TIMEOUT_SECONDS}s", pytrace=False)

    row = db.execute(
        "SELECT * FROM entity_research WHERE researched_at >= %s AND (entity_name ILIKE %s OR canonical_name ILIKE %s) "
        "ORDER BY researched_at DESC LIMIT 1",
        (started, f"%{case['entity_name']}%", f"%{case['entity_name']}%"),
    ).fetchone()
    failures = []
    if row is None:
        pytest.fail(f"[{case['id']}] no entity_research row was saved for {case['entity_name']}", pytrace=False)

    findings = row["findings"] or []
    concepts = {f.get("concept") for f in findings}
    if row["entity_kind"] != case["expect_kind"]:
        failures.append(f"entity_kind {row['entity_kind']!r}, expected {case['expect_kind']!r}")
    if not findings:
        failures.append("the row has no findings")
    if not concepts & set(case["expect_concepts_any"]):
        failures.append(f"found {sorted(c for c in concepts if c)}, none of {case['expect_concepts_any']}")
    for gap in row.get("gaps") or []:
        if gap.get("reason") not in {"blocked", "not_stated"} or not (gap.get("detail") or "").strip():
            failures.append(f"a gap without a reason or detail: {gap}")
    for f in findings:
        if f.get("concept") in TAGGED and (f.get("themes") or f.get("populations") or f.get("lenses")) \
                and not (f.get("tag_note") or "").strip():
            failures.append(f"a tagged {f['concept']} finding with no tag_note")
    summary = next((s for s in summaries if s.get("slug") == row["slug"]), None)
    if summary is None:
        failures.append(f"no researcher summary for {row['slug']}")
    elif summary["fact_count"] != len(findings):
        failures.append(f"the summary says {summary['fact_count']} facts, the row holds {len(findings)}")

    if failures:
        report = [f"[{case['id']}] {case['request']}", f"  row: {row['slug']} {row['status']} {len(findings)} facts"]
        pytest.fail("\n".join(report + [f"  FAIL: {f}" for f in failures]), pytrace=False)
