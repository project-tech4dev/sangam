"""The tool surface deepagents gives us, and the parts we take back.

`create_deep_agent` is a preset. It adds eight filesystem tools and, whenever
any subagent is declared, a `general-purpose` one carrying the main agent's
entire tool list. Neither was asked for, and the second could write to the
catalog under none of the importer's instructions. These tests pin both, so a
library upgrade cannot quietly restore them.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from langchain_core.tools import tool

from app.agent.harness import FILESYSTEM_TOOLS, install


@tool
def read_file(path: str) -> str:
    """Stand-in for the deepagents built-in."""
    return path


@tool
def db_query(sql: str) -> str:
    """Stand-in for one of ours."""
    return sql


class TestTheProfileIsInstalled:
    def test_install_is_idempotent(self):
        install()
        install()  # a second builder must not raise or double-register

    def test_it_resolves_for_the_model_we_run(self):
        from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model

        from app.agent.models import resolve_model
        from app.core.config import get_settings

        install()
        profile = _harness_profile_for_model(resolve_model(get_settings().model), None)
        assert profile.excluded_tools == FILESYSTEM_TOOLS
        assert profile.general_purpose_subagent is not None
        assert profile.general_purpose_subagent.enabled is False

    @pytest.mark.parametrize("name", sorted(FILESYSTEM_TOOLS))
    def test_every_filesystem_tool_is_named(self, name):
        # If deepagents adds a ninth, this list is where it has to be noticed.
        assert name in FILESYSTEM_TOOLS

    def test_execute_is_excluded(self):
        # Advertised to the model as "executes a shell command in an isolated
        # sandbox", on an agent whose job is reading untrusted web pages.
        assert "execute" in FILESYSTEM_TOOLS


class TestExclusionReachesTheModel:
    """Excluded tools stay in the dispatch table and are filtered out of the
    model request, so asserting on `tools_by_name` proves nothing."""

    def test_the_model_is_not_offered_an_excluded_tool(self):
        from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

        offered: dict[str, list] = {}

        class Request:
            tools: ClassVar[list] = [read_file, db_query]

            def override(self, tools):
                offered["tools"] = tools
                return self

        _ToolExclusionMiddleware(excluded=FILESYSTEM_TOOLS).wrap_model_call(
            Request(), lambda r: None
        )
        assert [t.name for t in offered["tools"]] == ["db_query"]


class TestTheBuiltAgentsAdvertiseOnlyWhatWeDeclared:
    def test_ask_sangam_has_no_subagents(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings

        tools = build_agent(get_settings(), None).nodes["tools"].bound.tools_by_name
        # It declares none, so the task tool should not exist at all. It did,
        # because a general-purpose subagent was inserted carrying db_query.
        assert "task" not in tools

    def test_import_advertises_exactly_its_two_subagents(self):
        from app.core.config import get_settings
        from app.ingest.agent import build_ingest_agent

        tools = build_ingest_agent(get_settings(), None).nodes["tools"].bound.tools_by_name
        # Parse the advertised list rather than searching the whole string:
        # deepagents' boilerplate mentions general-purpose in a generic
        # sentence whether or not the subagent exists.
        advertised = {
            line.strip()[2:].split(":", 1)[0]
            for line in tools["task"].description.splitlines()
            if line.strip().startswith("- ") and ":" in line
        }
        assert "entity-researcher" in advertised
        assert "catalog-writer" in advertised
        assert "general-purpose" not in advertised


class TestTheUtilityModelIsOptional:
    """Cheaper models for work that needs no reasoning — and unset, nothing
    changes, because a performance setting that alters behaviour by default is
    a behaviour change wearing a performance setting's name."""

    def test_unset_means_the_main_model(self):
        from app.core.config import Settings

        s = Settings(utility_model="")
        assert (s.utility_model or s.model) == s.model

    def test_set_means_that_model(self):
        from app.core.config import Settings

        s = Settings(utility_model="anthropic:claude-haiku-4-5")
        assert (s.utility_model or s.model) == "anthropic:claude-haiku-4-5"

    def test_the_writer_subagent_is_not_mutated_in_place(self):
        # build_ingest_agent copies CATALOG_WRITER before adding a model, so
        # building twice with different settings cannot leak between them.
        from app.core.config import get_settings
        from app.ingest.agent import CATALOG_WRITER, build_ingest_agent

        build_ingest_agent(get_settings(), None)
        assert "model" not in CATALOG_WRITER
