"""Gating for the agent evals: real model calls, so never by accident."""

from __future__ import annotations

import json
import os
import pathlib

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import Settings
from app.integrations.tracing import configure_langfuse

CASES_DIR = pathlib.Path(__file__).parent / "cases"
DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
# Evals may run against staging, so nothing they open can write.
READ_ONLY = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
# Where the agent evals leave {case id: output} and the Langfuse run URL for the summary.
SUMMARY_KEY = pytest.StashKey[tuple[dict, str | None]]()

# Which env var must hold a key for a given model provider.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}


def pytest_addoption(parser):
    parser.addoption(
        "--run-evals",
        action="store_true",
        default=False,
        help="run the agent evals (real model calls — these cost money)",
    )
    parser.addoption(
        "--eval-tag",
        action="store",
        default="",
        help="only run eval cases carrying this tag (e.g. canary)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-evals"):
        return
    skip = pytest.mark.skip(reason="agent eval; pass --run-evals to run (costs money)")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)


def load_cases(tag: str = "") -> list[dict]:
    cases = [
        json.loads(line)
        for path in sorted(CASES_DIR.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [c for c in cases if not tag or tag in c.get("tags", [])]


@pytest.fixture(scope="session")
def eval_settings() -> Settings:
    settings = Settings()
    provider = settings.model.split(":", 1)[0]
    key = PROVIDER_KEYS.get(provider)
    if key and not os.environ.get(key):
        pytest.skip(f"{key} is not set, so {settings.model} cannot be called")
    # Before any agent is built: the first Langfuse client wins, and one built later has no masking.
    if settings.langfuse_enabled and not configure_langfuse(settings):
        settings = settings.model_copy(update={"langfuse_public_key": "", "langfuse_secret_key": ""})
    return settings


def pytest_terminal_summary(terminalreporter, config):
    summary = config.stash.get(SUMMARY_KEY, None)
    if not summary:
        return
    results, url = summary
    write = terminalreporter.write_line
    write("")
    write(f"{'case':<34} {'pass':>4} {'tools':>5} {'model':>5} {'in tok':>8} {'cache rd':>8} {'out tok':>7} {'secs':>6}  calls")
    for case_id, out in results.items():
        s = out.get("stats", {})
        calls = " ".join(f"{t}×{n}" for t, n in sorted(s.get("tool_calls", {}).items()))
        write(
            f"{case_id[:34]:<34} {'ok' if not out.get('failures') else 'FAIL':>4} {s.get('total_tool_calls', 0):>5} "
            f"{s.get('model_calls', 0):>5} {s.get('input_tokens', 0):>8} {s.get('cache_read_tokens', 0):>8} "
            f"{s.get('output_tokens', 0):>7} {s.get('seconds', 0):>6}  {calls}"
        )
        for warning in out.get("warnings", []):
            write(f"{'':<34} note: {warning}")
    write(f"Langfuse run (cost per case, compare runs): {url}" if url else "Langfuse off: no run recorded")


async def read_only(conn) -> None:
    await conn.execute(READ_ONLY)


@pytest.fixture(scope="session")
def slug_ids() -> dict[str, str]:
    """slug -> id, for every citable entity."""
    try:
        with psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row) as conn:
            mapping = {}
            for kind, table in (("org", "orgs"), ("funder", "funders")):
                for row in conn.execute(f"SELECT id, slug FROM {table}").fetchall():
                    mapping[f"{kind}:{row['slug']}"] = f"{kind}:{row['id']}"
            return mapping
    except psycopg.OperationalError:
        pytest.skip("eval database not reachable (TEST_DATABASE_URL)")


@pytest.fixture(scope="session")
def db():
    try:
        with psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row, autocommit=True) as conn:
            conn.execute(READ_ONLY)
            yield conn
    except psycopg.OperationalError:
        pytest.skip("eval database not reachable (TEST_DATABASE_URL)")
