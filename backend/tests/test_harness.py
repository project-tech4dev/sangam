"""The tool surface deepagents gives us, and the parts we take back.

`create_deep_agent` is a preset. It adds eight filesystem tools and, whenever
any subagent is declared, a `general-purpose` one carrying the main agent's
entire tool list. Neither was asked for, and the second could write to the
catalog under none of the importer's instructions. These tests pin both, so a
library upgrade cannot quietly restore them.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import tool

from app.agent.harness import (
    FILESYSTEM_TOOLS,
    REQUIRED_MINIMUM,
    SKILL_READING_TOOLS,
    install,
)


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
        assert profile.general_purpose_subagent is not None
        assert profile.general_purpose_subagent.enabled is False

    def test_the_profile_does_not_decide_tools(self):
        # A profile is registered per PROVIDER, so it is global to every agent
        # sharing a model. Sangam Import needs read_file to load a skill and
        # Ask Sangam must not have it, so the tool surface is per-agent
        # middleware instead.
        from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model

        from app.agent.models import resolve_model
        from app.core.config import get_settings

        install()
        profile = _harness_profile_for_model(resolve_model(get_settings().model), None)
        assert not profile.excluded_tools

    @pytest.mark.parametrize("name", sorted(FILESYSTEM_TOOLS))
    def test_every_filesystem_tool_is_named(self, name):
        # If deepagents adds a ninth, this list is where it has to be noticed.
        assert name in FILESYSTEM_TOOLS

    def test_execute_is_excluded(self):
        # Advertised to the model as "executes a shell command in an isolated
        # sandbox", on an agent whose job is reading untrusted web pages.
        assert "execute" in FILESYSTEM_TOOLS


class TestTheFilesystemMiddlewareIsReplaced:
    """Our FilesystemMiddleware takes the default one's place by name, so an
    unwanted tool is never registered rather than merely hidden."""

    def test_only_the_named_tools_exist(self):
        from deepagents.backends.state import StateBackend

        from app.agent.harness import filesystem

        assert [t.name for t in filesystem(StateBackend()).tools] == ["read_file"]
        kept = {t.name for t in filesystem(StateBackend(), keep=SKILL_READING_TOOLS).tools}
        assert kept == {"read_file", "ls"}

    def test_nothing_that_writes_is_ever_kept(self):
        # read_file is the floor: FilesystemMiddleware refuses to be built
        # without it. Everything that mutates is gone from both agents.
        assert not set(SKILL_READING_TOOLS) & {"write_file", "edit_file", "delete", "execute"}
        assert not set(REQUIRED_MINIMUM) & {"write_file", "edit_file", "delete", "execute"}


class TestTheBuiltAgentsAdvertiseOnlyWhatWeDeclared:
    def test_ask_sangam_has_no_subagents(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings

        tools = build_agent(get_settings(), None).nodes["tools"].bound.tools_by_name
        # It declares none, so the task tool should not exist at all. It did,
        # because a general-purpose subagent was inserted carrying db_query.
        assert "task" not in tools

    def test_ask_sangam_holds_its_six_tools_and_the_mandatory_one(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings

        tools = set(build_agent(get_settings(), None).nodes["tools"].bound.tools_by_name)
        assert tools == {
            "db_list_tables", "db_describe_table", "db_profile_column", "db_query",
            "search_graph", "fetch_url", "read_file",
        }

    def test_neither_agent_can_write_a_file_or_run_a_command(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings
        from app.ingest.agent import build_ingest_agent

        forbidden = {"write_file", "edit_file", "delete", "execute", "glob", "grep"}
        for build in (build_agent, build_ingest_agent):
            tools = set(build(get_settings(), None).nodes["tools"].bound.tools_by_name)
            assert not tools & forbidden, f"{build.__name__}: {sorted(tools & forbidden)}"

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


class TestTheSkillIsFoundAndIsProgressive:
    """A skill the model cannot reach is dead weight in the prompt; a skill it
    loads on every turn is the prompt with extra steps."""

    def test_the_skills_directory_ships_inside_the_package(self):
        from app.ingest.agent import SKILLS_DIR

        # Inside app/, so it rides the ./backend/app mount and the image's
        # `COPY app/ app/`. Outside it, a skill would exist on neither.
        assert SKILLS_DIR.is_dir()
        assert "app/ingest/skills" in SKILLS_DIR.as_posix()

    def test_every_skill_is_one_directory_deep_with_matching_frontmatter(self):
        import yaml

        from app.ingest.agent import SKILLS_DIR

        # Discovery is exactly one level: ls the source, then look for
        # <dir>/SKILL.md. A nested one is never found, and neither is a
        # SKILL.md at the root.
        found = list(SKILLS_DIR.glob("*/SKILL.md"))
        assert found, "no skills discovered where the middleware will look"
        for path in found:
            head = path.read_text(encoding="utf-8").split("---")[1]
            meta = yaml.safe_load(head)
            assert meta["name"] == path.parent.name, (
                f"{path}: name {meta['name']!r} must equal its directory"
            )
            assert len(meta["description"]) <= 1024, "truncated in the prompt above 1024"
            # The description is all the model sees before deciding to load,
            # so it says WHEN to use the skill, not what it is.
            assert "use when" in meta["description"].lower()

    def test_the_route_round_trips(self):
        from app.ingest.agent import SKILLS_ROUTE, _backend

        # ls strips the prefix, the routed backend lists its own root, and the
        # composite prepends it back — so the path printed in the prompt is
        # the path the model's read_file resolves.
        backend = _backend()
        listed = backend.ls(SKILLS_ROUTE)
        assert listed.error is None
        paths = [e["path"] for e in (listed.entries or [])]
        assert paths and all(p.startswith(SKILLS_ROUTE) for p in paths)

        target = f"{paths[0].rstrip('/')}/SKILL.md"
        downloaded = backend.download_files([target])[0]
        assert downloaded.error is None
        content = downloaded.content or b""
        text = content if isinstance(content, str) else content.decode("utf-8")
        assert "name:" in text

    def test_the_researcher_declares_its_own_sources(self):
        from app.ingest.agent import ENTITY_RESEARCHER, SKILLS_ROUTE

        # An isolated subagent inherits none of the parent's skills.
        assert ENTITY_RESEARCHER["skills"] == [SKILLS_ROUTE]
