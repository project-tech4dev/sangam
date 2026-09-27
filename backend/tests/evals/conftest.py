"""Gating for the agent evals: real model calls, so never by accident."""

from __future__ import annotations

import json
import os
import pathlib

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import Settings

CASES_DIR = pathlib.Path(__file__).parent / "cases"
DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

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
    return settings


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
        pytest.skip("compose Postgres not reachable on localhost:5433")


@pytest.fixture(scope="session")
def db():
    try:
        with psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row) as conn:
            yield conn
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
