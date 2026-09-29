"""Unit tests for the importer: no database, no network, no model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ingest.matcher import CORE_FLOOR, Match, core, core_similarity
from app.ingest.records import FunderCsrYearRecord, FunderRecord, NewsMentionRecord
from app.ingest.sources import SOURCES, AccessRule, Category, dispatchable, resolve
from app.ingest.writer import _diff, slugify

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def prov(**kw):
    return {"source_url": "https://indiacsr.in/a", "source_name": "indiacsr", "fetched_at": NOW, **kw}


class TestSourcesGateOnAccessRules:
    def test_only_open_api_and_crawl_allowed_are_dispatchable(self):
        # A rule, not a fixed set: the registry grows, the rule must not.
        allowed = {AccessRule.OPEN_API, AccessRule.CRAWL_ALLOWED}
        assert {s.access_rule for s in dispatchable()} <= allowed
        assert all(s.access_rule in allowed for s in SOURCES.values() if s.dispatchable)

    def test_only_sources_with_an_adapter_are_actually_fetched(self):
        """Permitted and built are different things, and the run report says which."""
        from app.ingest.runner import ADAPTERS

        assert set(ADAPTERS) == {"india_csr", "gdelt"}
        assert set(ADAPTERS) <= {s.key for s in dispatchable()}, "an adapter for a held source"

    def test_a_dispatchable_source_names_a_host_and_a_robots_check(self):
        # Something a crawler will visit has to say where, and when someone looked.
        for source in dispatchable():
            assert source.host, f"{source.key} is dispatchable with no host"
            assert source.robots_checked_at, f"{source.key} has no recorded robots check"

    def test_the_strictest_rule_on_a_host_wins(self):
        """mcacdm.nic.in carries four products. First-match-wins would let
        declaration order decide whether a crawler runs."""
        from app.ingest.sources import rule_for_host, sources_on_host

        assert len(sources_on_host("mcacdm.nic.in")) > 1
        rule, _ = rule_for_host("mcacdm.nic.in")
        assert rule == AccessRule.NO_SCRAPING
        assert rule_for_host("example.invalid") is None

    def test_every_source_belongs_to_a_category(self):
        for source in SOURCES.values():
            assert source.categories, f"{source.key} belongs to no category"
            assert all(isinstance(c, Category) for c in source.categories)

    def test_the_registry_self_checks_at_import(self):
        """The JSON is loaded, so a malformed entry must fail loudly rather than
        producing a registry that is quietly wrong."""
        from app.ingest import sources as module

        assert module._self_check() is None

    @pytest.mark.parametrize("key", ["give", "mca_csr", "csrbox"])
    def test_a_restricted_source_is_registered_but_never_dispatched(self, key):
        source = SOURCES[key]
        assert not source.dispatchable
        assert source.basis, "a refusal has to carry its evidence, not just its verdict"

    def test_every_source_states_the_basis_for_its_rule(self):
        # The rule alone is a verdict; the basis is what a reviewer can check.
        for source in SOURCES.values():
            assert len(source.basis) > 40, f"{source.key} has no real basis"
            assert source.access_rule in set(AccessRule)

    def test_an_unknown_source_name_is_reported_not_ignored(self):
        known, unknown = resolve(["india_csr", "nonesuch"])
        assert [s.key for s in known] == ["india_csr"]
        assert unknown == ["nonesuch"]


class TestRecordsRefuseWhatTheWriterCannotUse:
    def test_a_fact_without_a_source_is_rejected(self):
        with pytest.raises(ValidationError):
            FunderRecord(name="Acme Foundation", source_name="x", fetched_at=NOW)

    def test_source_url_must_be_a_url(self):
        with pytest.raises(ValidationError, match="http"):
            FunderRecord(name="Acme", **prov(source_url="indiacsr.in/a"))

    @pytest.mark.parametrize("bad", ["FY24", "2023-24", "FY2023-2024", "fy2023-24"])
    def test_fiscal_year_format_is_enforced_before_the_database_sees_it(self, bad):
        with pytest.raises(ValidationError, match="FY2023-24"):
            FunderCsrYearRecord(funder_name="Acme Ltd", fiscal_year=bad, **prov())

    def test_a_negative_csr_amount_is_rejected(self):
        with pytest.raises(ValidationError):
            FunderCsrYearRecord(funder_name="Acme Ltd", fiscal_year="FY2024-25", total_spent=-1, **prov())

    def test_an_unknown_identifier_type_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown identifier types"):
            FunderRecord(name="Acme", identifiers={"aadhaar": "1234"}, **prov())

    def test_a_good_record_carries_its_provenance_through(self):
        rec = FunderCsrYearRecord(
            funder_name="Axis Bank Limited", fiscal_year="FY2024-25", total_spent=286.92,
            **prov(as_of="FY2024-25"),
        )
        assert (rec.as_of, rec.source_name, rec.total_spent) == ("FY2024-25", "indiacsr", 286.92)


class TestMatchingOnTheDistinctivePartOfAName:
    def test_boilerplate_is_stripped(self):
        assert core("Bata India Limited") == "bata"
        assert core("The Tata Trusts") == "tata"

    def test_an_all_boilerplate_name_falls_back_to_the_whole_string(self):
        # Otherwise every "India Foundation" would match every other one exactly.
        assert core("India Foundation") == "india foundation"

    @pytest.mark.parametrize(
        ("a", "b"),
        [("Bata India Limited", "BASF India Limited"),   # the bug this floor exists for
         ("SBI Foundation", "HDFC Foundation"),
         ("Infosys Foundation", "Wipro Foundation")],
    )
    def test_two_unrelated_firms_are_not_proposed_as_each_other(self, a, b):
        assert core_similarity(a, b) < CORE_FLOOR

    @pytest.mark.parametrize(
        ("a", "b"), [("Axis Bank Ltd", "Axis Bank Limited"), ("Tata Trusts", "Tata Trust")]
    )
    def test_the_same_firm_spelled_differently_is_proposed(self, a, b):
        assert core_similarity(a, b) >= CORE_FLOOR

    def test_a_foundation_is_not_its_parent_company(self):
        # They are separate rows linked by funders.parent_id, so this must NOT match.
        assert core_similarity("Reliance Foundation", "Reliance Industries Limited") < CORE_FLOOR

    def test_only_identifier_and_exact_matches_resolve(self):
        assert Match("identifier", 3).resolved
        assert Match("exact", 3).resolved
        assert not Match("trigram", None, 0.9, [{"id": 3}]).resolved
        assert not Match("none").resolved


class TestWriterDiff:
    def test_a_proposed_null_never_erases_a_stored_value(self):
        assert _diff({"website": "https://a.org"}, {"website": None}) == {}

    def test_an_unchanged_value_is_not_an_update(self):
        assert _diff({"total_spent": 100.0}, {"total_spent": 100.0}) == {}

    def test_whitespace_is_not_a_change(self):
        assert _diff({"name": "Axis Bank "}, {"name": "Axis Bank"}) == {}

    def test_a_real_change_records_both_sides(self):
        assert _diff({"total_spent": 100.0}, {"total_spent": 120.5}) == {
            "total_spent": {"old": 100.0, "new": 120.5}
        }

    def test_slug_is_url_safe(self):
        assert slugify("Axis Bank Foundation (India)") == "axis-bank-foundation-india"


class TestNewsMentionRecord:
    def test_gdelt_rows_need_only_a_url_and_provenance(self):
        rec = NewsMentionRecord(url="https://x.in/a", **prov(source_url="https://x.in/a"))
        assert rec.kind == "news_mention"


class TestIngestAgentIsSelfDescribing:
    """Same rule Ask Sangam has: a tool the instructions never name is a tool the
    model will not reach for."""

    def test_instructions_name_every_registered_tool(self):
        from app.ingest.agent import INSTRUCTIONS, TOOLS

        missing = [t.name for t in TOOLS if t.name not in INSTRUCTIONS]
        assert not missing, f"registered but never mentioned in instructions.md: {missing}"

    def test_instructions_are_loaded_not_empty(self):
        from app.ingest.agent import INSTRUCTIONS

        assert len(INSTRUCTIONS.strip()) > 500
        assert "Sangam Import" in INSTRUCTIONS

    def test_every_tool_defined_is_also_registered(self):
        """The reverse of the rule above, and the one that actually bit: plan_import
        was written, documented and unreachable, because nothing added it to TOOLS."""
        import inspect

        from langchain_core.tools import BaseTool

        from app.ingest import research, tools
        from app.ingest.agent import TOOLS

        # Both modules: the importing tools live in tools.py and the reading
        # tools in research.py, so equality on one module would be wrong.
        defined = {
            obj.name
            for module in (tools, research)
            for _, obj in inspect.getmembers(module)
            if isinstance(obj, BaseTool)
        }
        registered = {t.name for t in TOOLS}
        assert not defined - registered, f"defined but never registered: {sorted(defined - registered)}"

    def test_planning_comes_before_writing(self):
        from app.ingest.agent import TOOLS

        names = [t.name for t in TOOLS]
        assert names.index("plan_import") < names.index("run_import_now")

    def test_the_importer_has_no_sql_tool(self):
        # The whole safety argument: this agent proposes typed records and the
        # writer does the SQL. A db_query here would undo that.
        from app.ingest.agent import TOOLS

        assert not [t for t in TOOLS if "query" in t.name or "sql" in t.name]
