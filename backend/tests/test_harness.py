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
        # sharing a model. Both supervisors need ls to find a skill and no
        # subagent may hold it, so the tool surface is per-agent middleware
        # instead.
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
    def test_ask_sangam_advertises_exactly_the_funder_assessor(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings

        tools = build_agent(get_settings(), None).nodes["tools"].bound.tools_by_name
        # The task tool exists for the assessor alone. It once carried a
        # general-purpose subagent with db_query and no instructions.
        advertised = {
            line.strip()[2:].split(":", 1)[0]
            for line in tools["task"].description.splitlines()
            if line.strip().startswith("- ") and ":" in line
        }
        assert "funder-assessor" in advertised
        assert "general-purpose" not in advertised

    def test_ask_sangam_holds_its_six_tools_the_skill_readers_and_task(self):
        from app.agent.build import build_agent
        from app.core.config import get_settings

        tools = set(build_agent(get_settings(), None).nodes["tools"].bound.tools_by_name)
        assert tools == {
            "db_list_tables", "db_describe_table", "db_profile_column", "db_query",
            "search_graph", "fetch_url", "read_file", "ls", "task",
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

    def test_no_subagent_declares_any(self):
        """Skills are output procedures, and a subagent has no output to shape.

        The researcher used to declare the route — an isolated subagent
        inherits nothing, so it had to be declared or not held at all. But its
        targets come from research_goals, derived from the schema, and the one
        thing a skill could add is a brief format it cannot produce: it returns
        a ResearchSummary with no prose. The supervisor writes the brief, so
        the supervisor holds the skills.
        """
        from app.ingest.agent import CATALOG_WRITER, ENTITY_RESEARCHER

        for spec in (ENTITY_RESEARCHER, CATALOG_WRITER):
            assert "skills" not in spec, spec["name"]

    def test_every_skill_is_advertised_to_the_supervisor(self):
        """Pinned as a literal set, not a count, because the hazard is a skill
        that overlaps another's trigger: the model picks between them on the
        description alone. Two per stage of the run, split by entity kind
        where the kinds genuinely differ — an NGO brief is not a funder scan
        with fewer rows; it opens on 12A, 80G and CSR-1, which no funder table
        holds — plus the three that are the same job either way.
        """
        from app.ingest.agent import SKILLS_DIR

        names = {d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").exists()}
        assert names == {
            # what to pull, per kind
            "funder-intake-research",
            "ngo-credential-research",
            # the record for one organisation, either kind
            "entity-record",
            # onto the catalog, and back out again
            "catalog-mapping",
            "catalog-write-report",
            # the comparison across several, per kind
            "funder-scan-for-fundraisers",
            "ngo-brief-for-funders",
        }


def _subagent_tools(graph) -> dict[str, set[str]]:
    """What each subagent's own graph runs — which is not what its spec declares."""
    # deepagents 0.7.16 keeps compiled subagents only in the task tool's
    # closure; an upgrade that moves them must fail here, not pass silently.
    task = graph.nodes["tools"].bound.tools_by_name["task"]
    found: dict[str, set[str]] = {}
    for cell in (task.func or task.coroutine).__closure__ or ():
        value = cell.cell_contents
        if not isinstance(value, dict):
            continue
        for name, sub in value.items():
            if "tools" in getattr(sub, "nodes", {}):
                found[name] = set(sub.nodes["tools"].bound.tools_by_name)
    assert found, "no compiled subagent graphs found — deepagents moved them"
    return found


@pytest.fixture(scope="module")
def subagents() -> dict[str, set[str]]:
    from app.core.config import get_settings
    from app.ingest.agent import build_ingest_agent

    return _subagent_tools(build_ingest_agent(get_settings(), None))


class TestASubagentRunsOnlyTheToolsItsSpecDeclares:
    """The parent's restricted filesystem does not reach an isolated subagent.

    deepagents builds it a stack of its own with an unrestricted
    FilesystemMiddleware, so both subagents ran write_file, edit_file and
    delete against the backend whose /skills/ route is real disk.
    """

    def test_both_subagents_are_compiled_and_found(self, subagents):
        assert set(subagents) == {"entity-researcher", "catalog-writer"}

    def test_neither_subagent_can_write_a_file_or_run_a_command(self, subagents):
        forbidden = {"write_file", "edit_file", "delete", "execute", "glob", "grep"}
        for name, tools in subagents.items():
            assert not tools & forbidden, f"{name}: {sorted(tools & forbidden)}"

    def test_the_researcher_gets_its_seven_and_nothing_of_the_filesystem(self, subagents):
        assert subagents["entity-researcher"] == {
            "research_goals", "funder_dossier", "search_public_sources",
            "read_page", "fetch_document", "read_document_pages", "save_research",
            "read_file",
        }

    def test_the_writer_gets_the_floor_and_not_the_skill_reader(self, subagents):
        assert subagents["catalog-writer"] == {"promote_research", "funder_dossier", "read_file"}

    def test_neither_gets_ls_because_neither_loads_a_skill(self, subagents):
        # read_file is left on both only because FilesystemMiddleware refuses
        # to be constructed without it. `ls` is how a skill is discovered, and
        # skills are the supervisor's — so on a subagent it is dead weight
        # pointing at the one backend route that is real disk.
        for name, tools in subagents.items():
            assert "ls" not in tools, name


class TestTheAssessorReadsAndNothingElse:
    """An isolated subagent builds its own stack, so Ask's restricted filesystem
    does not reach it. Unset, it would run write_file and execute."""

    @pytest.fixture(scope="class")
    def assessor(self) -> set[str]:
        from app.agent.build import build_agent
        from app.core.config import get_settings

        return _subagent_tools(build_agent(get_settings(), None))["funder-assessor"]

    def test_it_runs_three_read_only_sql_tools_and_the_floor(self, assessor):
        assert assessor == {"db_list_tables", "db_describe_table", "db_query", "read_file"}

    def test_it_cannot_fetch_the_web_or_launch_another_subagent(self, assessor):
        assert not assessor & {"fetch_url", "search_graph", "task"}


class TestTheAssessorModelIsOptional:
    def test_unset_leaves_the_spec_on_the_main_model(self):
        from app.agent.build import ASSESSOR, build_agent
        from app.core.config import Settings

        build_agent(Settings(assessor_model=""), None)
        assert "model" not in ASSESSOR

    def test_set_is_not_written_into_the_shared_spec(self):
        from app.agent.build import ASSESSOR, build_agent
        from app.core.config import Settings

        build_agent(Settings(assessor_model="anthropic:claude-haiku-4-5"), None)
        assert "model" not in ASSESSOR


class TestAskSangamLoadsItsMatchingProcedureFromSkills:
    """Import's mechanism, Ask's own directory: procedures load on demand, rules stay in the prompt."""

    def test_the_skills_directory_ships_inside_the_package(self):
        from app.agent.build import SKILLS_DIR

        assert SKILLS_DIR.is_dir()
        assert "app/agent/skills" in SKILLS_DIR.as_posix()

    def test_every_skill_has_frontmatter_that_says_when(self):
        import yaml

        from app.agent.build import SKILLS_DIR

        found = list(SKILLS_DIR.glob("*/SKILL.md"))
        assert found
        for path in found:
            meta = yaml.safe_load(path.read_text(encoding="utf-8").split("---")[1])
            assert meta["name"] == path.parent.name
            assert len(meta["description"]) <= 1024
            assert "use when" in meta["description"].lower()

    def test_the_route_round_trips(self):
        from app.agent.build import SKILLS_ROUTE, _backend

        backend = _backend()
        listed = backend.ls(SKILLS_ROUTE)
        assert listed.error is None
        paths = [e["path"] for e in (listed.entries or [])]
        assert paths and all(p.startswith(SKILLS_ROUTE) for p in paths)
        downloaded = backend.download_files([f"{paths[0].rstrip('/')}/SKILL.md"])[0]
        assert downloaded.error is None

    def test_the_three_matching_skills_and_no_others(self):
        from app.agent.build import SKILLS_DIR

        names = {d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").exists()}
        assert names == {"funder-matching", "funder-shortlist-brief", "funder-comparison"}

    def test_the_assessor_declares_none(self):
        # Its prompt is the criteria; a skill it might not load cannot be one.
        from app.agent.build import ASSESSOR

        assert "skills" not in ASSESSOR

    def test_a_skill_never_names_a_wave_size(self):
        # SKILL.md is read raw from disk, so a number there would ignore MAX_PARALLEL_RESEARCH.
        import re

        from app.agent.build import SKILLS_DIR

        for path in SKILLS_DIR.glob("*/SKILL.md"):
            assert not re.search(r"waves? of \d", path.read_text(encoding="utf-8")), path
