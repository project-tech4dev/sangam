"""Unit tests for the importer: no database, no network, no model."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.ingest.agent import CATALOG_WRITER
from app.ingest.expectations import (
    CONCEPT_TABLES,
    concepts_for,
    expected_fields,
    recent_fiscal_years,
)
from app.ingest.geography import _STATES, canonical_state
from app.ingest.matcher import (
    CORE_FLOOR,
    Match,
    core,
    core_similarity,
    same_but_for_boilerplate,
)
from app.ingest.promote import (
    CONCEPT_RECORDS,
    MERGEABLE,
    NOT_WRITTEN,
    PROMOTABLE,
    RENAMED,
    WRITE_ORDER,
    _row_identity,
    promote,
)
from app.ingest.records import (
    ContactRecord,
    FunderCsrSpendRecord,
    FunderCsrYearRecord,
    FunderFootprintRecord,
    FunderPartnerRecord,
    FunderRecord,
    MetricRecord,
    NewsMentionRecord,
    ProgramRecord,
    RfpRecord,
)
from app.ingest.research_records import (
    CONCEPTS,
    FINDING_MODELS,
    SCHEMA_VERSION,
    ContactFinding,
    CsrSpendFinding,
    CsrYearFinding,
    EntityResearch,
    FootprintFinding,
    MetricFinding,
    Money,
    PartnerFinding,
    PromotionReport,
    ResearchSummary,
    to_inr,
)
from app.ingest.sources import SOURCES, AccessRule, Category, dispatchable, resolve
from app.ingest.taxonomy import clause_for
from app.ingest.tools.research_tools import save_research
from app.ingest.writer import CSR_YEAR_UPDATABLE, _diff, slugify

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

    @pytest.mark.parametrize(
        ("a", "b"),
        [("Axis Bank", "Axis Bank Limited"), ("Axis Bank Ltd", "Axis Bank Limited"),
         ("Azim Premji Foundation", "Azim Premji Trust")],
    )
    def test_the_same_name_plus_boilerplate_resolves_rather_than_queueing(self, a, b):
        """Queueing these fragments one funder's years across two rows."""
        assert same_but_for_boilerplate(a, b)

    @pytest.mark.parametrize(
        ("a", "b"),
        [("Tata Trusts", "Tata Foundation"),      # both reduce to 'tata'
         ("SBI Foundation", "SBI Trust"),
         ("Reliance Foundation", "Reliance Industries Limited")],
    )
    def test_a_one_word_core_still_needs_a_person(self, a, b):
        """With a single distinctive token the boilerplate is what tells two
        organisations apart, so it cannot be discarded."""
        assert not same_but_for_boilerplate(a, b)

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

    def test_a_tool_is_never_reachable_only_through_a_skill(self):
        """The rule this test exists for — "a tool the instructions never name
        is a tool the model will not reach for" — applies just as much to a
        skill the model may decide not to load. So the always-on prompt has to
        name every tool, and a skill may only add detail."""
        from app.ingest.agent import INSTRUCTIONS, TOOLS

        for tool in TOOLS:
            assert tool.name in INSTRUCTIONS, (
                f"{tool.name} is not in instructions.md. Naming it only in a SKILL.md "
                f"makes it invisible whenever that skill is not loaded."
            )

    def test_instructions_are_loaded_not_empty(self):
        from app.ingest.agent import INSTRUCTIONS

        assert len(INSTRUCTIONS.strip()) > 500
        assert "Sangam Import" in INSTRUCTIONS

    def test_every_tool_defined_is_also_registered(self):
        """The reverse of the rule above, and the one that actually bit: plan_import
        was written, documented and unreachable, because nothing added it to TOOLS."""
        import importlib
        import inspect
        import pkgutil

        from langchain_core.tools import BaseTool

        from app.ingest import tools
        from app.ingest.agent import TOOLS

        # Every module in app/ingest/tools/, discovered rather than listed: a
        # fourth one added later is covered without anyone remembering to.
        defined = {
            obj.name
            for info in pkgutil.iter_modules(tools.__path__)
            for _, obj in inspect.getmembers(importlib.import_module(f"{tools.__name__}.{info.name}"))
            if isinstance(obj, BaseTool)
        }

        # A subagent's tools are registered too — reachable through `task`,
        # not on the main agent. save_research is the researcher's, by design.
        from app.ingest.agent import ENTITY_RESEARCHER

        registered = {t.name for t in TOOLS} | {t.name for t in ENTITY_RESEARCHER["tools"]}
        assert not defined - registered, f"defined but never registered: {sorted(defined - registered)}"
        # The other direction, which is the property the package exists to give:
        # a tool the model can call is a file in app/ingest/tools/, always.
        assert not registered - defined, (
            f"registered but defined outside app/ingest/tools/: {sorted(registered - defined)}"
        )

    def test_planning_comes_before_writing(self):
        from app.ingest.agent import TOOLS

        names = [t.name for t in TOOLS]
        assert names.index("plan_import") < names.index("run_import_now")

    def test_the_importer_has_no_sql_tool(self):
        # The whole safety argument: this agent proposes typed records and the
        # writer does the SQL. A db_query here would undo that.
        from app.ingest.agent import TOOLS

        assert not [t for t in TOOLS if "query" in t.name or "sql" in t.name]


class TestAMarketIsNotAFunder:
    """A real sentence with a real number and no organisation in it."""

    @pytest.mark.parametrize(
        "name",
        ["NSE-listed companies", "India Inc", "Top 100 companies", "Indian corporates",
         "the IT sector", "Listed PSUs"],
    )
    def test_an_aggregate_is_refused(self, name):
        with pytest.raises(ValidationError, match="not one organisation"):
            FunderCsrYearRecord(funder_name=name, fiscal_year="FY2024-25", **prov())

    @pytest.mark.parametrize(
        "name",
        ["Axis Bank Limited", "State Bank of India", "Infosys Ltd.", "Tata Steel Ltd.",
         "Azim Premji Foundation"],
    )
    def test_a_real_organisation_is_kept(self, name):
        assert FunderCsrYearRecord(funder_name=name, fiscal_year="FY2024-25", **prov())


class TestResearchRecords:
    """Every finding carries the sentence behind it, or it is not a finding."""

    def finding(self, **kw):
        base = {
            "concept": "csr_year", "fiscal_year": "FY2024-25",
            "total_spent": {"value": 427.0, "unit": "crore", "text": "Rs 427 crore"},
            "evidence": "The Bank spent Rs 427 crore on CSR activities during FY2024-25.",
            "source_url": "https://axis.bank.in/report.pdf", "confidence": "high",
        }
        return CsrYearFinding(**{**base, **kw})

    def test_a_finding_needs_a_real_sentence(self):
        with pytest.raises(ValidationError):
            self.finding(evidence="spent 427cr")

    def test_a_finding_needs_a_reachable_source(self):
        with pytest.raises(ValidationError, match="http"):
            self.finding(source_url="the annual report")

    def test_fiscal_year_format_is_enforced_here_too(self):
        with pytest.raises(ValidationError, match="FY2023-24"):
            self.finding(fiscal_year="FY25")

    def test_complete_with_nothing_found_is_a_contradiction(self):
        with pytest.raises(ValidationError, match="complete"):
            EntityResearch(entity_name="Acme Ltd", status="complete", summary="A" * 25)

    @pytest.mark.parametrize("status", ["partial", "wrong_entity"])
    def test_stopping_early_has_to_say_why(self, status):
        with pytest.raises(ValidationError, match="stopped_reason"):
            EntityResearch(entity_name="Acme Ltd", status=status, summary="A" * 25)

    def test_not_found_stands_on_its_own(self):
        # The one status that needs neither findings nor a reason.
        assert EntityResearch(entity_name="Acme Ltd", status="not_found", summary="A" * 25)

    def test_unknown_concepts_are_refused(self):
        with pytest.raises(ValidationError, match="unknown concepts"):
            EntityResearch(
                entity_name="Acme Ltd", status="not_found", summary="A" * 25,
                not_found=["csr_year", "vibes"],
            )

    def test_findings_are_reachable_by_concept(self):
        r = EntityResearch(
            entity_name="Acme Ltd", status="complete", summary="A" * 25,
            findings=[
                self.finding(),
                PartnerFinding(
                    fiscal_year="FY2024-25", partner_name="Harsha Trust", partner_kind="ngo",
                    evidence="Harsha Trust implemented the livelihoods programme in FY2024-25.",
                    source_url="https://axis.bank.in/report.pdf", confidence="high",
                ),
            ],
        )
        assert len(r.by_concept("csr_year")) == 1
        assert r.by_concept("grant") == []
        assert r.concepts_found() == ["csr_year", "partner"]


class TestDocRendering:
    """Generated blocks refresh; everything around them is left alone."""

    def test_only_the_marked_block_is_replaced(self):
        from app.ingest.render_docs import replace_block

        text = (
            "# KABIL\n\nHand-written analysis above.\n\n"
            "<!-- generated:funders -->\nOLD TABLE\n<!-- /generated -->\n\n"
            "Hand-written analysis below.\n"
        )
        out = replace_block(text, "funders", "NEW TABLE")
        assert "NEW TABLE" in out and "OLD TABLE" not in out
        assert "Hand-written analysis above." in out
        assert "Hand-written analysis below." in out

    def test_a_missing_block_is_appended_not_lost(self):
        from app.ingest.render_docs import replace_block

        out = replace_block("# KABIL\n\nJust prose.\n", "funders", "TABLE")
        assert "Just prose." in out and "TABLE" in out

    def test_rendering_twice_changes_nothing(self):
        from app.ingest.render_docs import replace_block

        once = replace_block("# X\n\nprose\n", "funders", "TABLE")
        assert replace_block(once, "funders", "TABLE") == once

    def test_amounts_read_as_crore(self):
        from app.ingest.render_docs import _crore

        # Stored in INR because the column says so; shown in crore because a
        # reader thinks in crore.
        assert _crore("4270000000") == "₹427.00 cr"
        assert _crore("not a number") == "not a number"


class TestExpectationsComeFromTheSchema:
    """The research targets are derived from the SQL catalog, not a second list."""

    def test_every_concept_maps_to_a_catalogued_table(self):
        from app.agent.tools.sql.catalog import CATALOG

        for concept, table in CONCEPT_TABLES.items():
            assert table in CATALOG, f"{concept} targets {table}, which is not catalogued"

    def test_the_concept_vocabulary_and_the_table_map_agree(self):
        # Both lists are hand-written in different modules; a concept with no
        # table is a finding with nowhere to go.
        assert set(CONCEPTS) == set(CONCEPT_TABLES)

    def test_stated_geography_and_footprint_are_different_concepts(self):
        # A priority is not a spend. Collapsing them is the error the whole
        # agent brief is built to prevent.
        assert CONCEPT_TABLES["stated_geography"] == "funder_locations"
        assert CONCEPT_TABLES["footprint"] == "funder_footprints"

    def test_surrogate_keys_and_provenance_are_never_research_targets(self):
        for concept in CONCEPT_TABLES:
            names = {f.name for f in expected_fields(concept)}
            assert "id" not in names
            assert not names & {"source_url", "fetched_at", "document_id", "content_hash"}
            # A raw foreign key is the writer's job; only the named forms survive.
            assert not any(n.endswith("_id") for n in names), concept

    def test_a_named_foreign_key_survives_as_a_name(self):
        names = {f.name for f in expected_fields("csr_spend")}
        assert {"state", "district"} <= names
        assert "state_location_id" not in names

    def test_required_fields_are_marked(self):
        required = {f.name for f in expected_fields("csr_spend") if f.required}
        assert required == {"fiscal_year", "amount"}

    def test_enum_values_reach_the_researcher(self):
        kind = next(f for f in expected_fields("partner") if f.name == "partner_kind")
        assert "ngo" in kind.values and "armed_forces" in kind.values
        assert "one of:" in kind.describe()

    def test_an_ngo_is_not_offered_the_funder_only_concepts(self):
        assert "csr_year" not in concepts_for("org")
        assert "csr_year" in concepts_for("funder")

    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            # April onwards, last April-to-March year has closed.
            (date(2026, 9, 29), "FY2025-26"),
            # Before April, it has not.
            (date(2026, 2, 1), "FY2024-25"),
        ],
    )
    def test_the_newest_year_asked_for_is_one_that_has_ended(self, today, expected):
        years = recent_fiscal_years(today)
        assert years[0] == expected
        assert len(years) == 3


class TestPromotionRefusesWhatItCannotWrite:
    async def test_an_ngo_is_not_written_into_funders(self):
        # orgs has no writer. Promoting an org row would put an NGO in the
        # funder table, which is a wrong answer carrying a catalog citation.
        row = {
            "slug": "the-ant", "entity_name": "The ANT", "canonical_name": None,
            "entity_kind": "org", "researched_at": NOW, "schema_version": 2,
            "findings": [{"concept": "identity", "name": "The Ant",
                          "source_url": "https://theant.org",
                          "evidence": "The Ant is a registered society working in Assam.",
                          "confidence": "high"}],
        }
        report = await promote(None, row)
        assert report["funder"] is None
        assert any("no writer" in r for r in report["reasons"])


class TestFindingsAreShapedLikeTheRowsTheyBecome:
    """The models and the schema are held together mechanically, not by memory.

    A migration that adds a column changes expected_fields() the next time it
    runs, and these fail until someone decides whether a researcher can find it.
    """

    EVIDENCE = frozenset({"concept", "evidence", "source_url", "source_name", "confidence", "basis"})

    def fields_of(self, concept: str) -> set[str]:
        return set(FINDING_MODELS[concept].model_fields) - self.EVIDENCE

    def test_every_concept_has_a_model(self):
        assert set(FINDING_MODELS) == set(CONCEPT_TABLES)

    @pytest.mark.parametrize("concept", sorted(CONCEPT_TABLES))
    def test_the_model_carries_exactly_what_the_table_expects(self, concept):
        want = {f.name for f in expected_fields(concept)}
        assert self.fields_of(concept) == want

    @pytest.mark.parametrize("concept", sorted(CONCEPT_TABLES))
    def test_a_required_column_is_a_required_field(self, concept):
        model = FINDING_MODELS[concept]
        for expected in expected_fields(concept):
            if not expected.required:
                continue
            field = model.model_fields[expected.name]
            assert field.is_required(), (
                f"{concept}.{expected.name} is NOT NULL in the schema but optional on the model, "
                f"so a finding can be saved that no writer can ever store"
            )

    def test_every_finding_still_needs_its_sentence(self):
        with pytest.raises(ValidationError):
            CsrSpendFinding(
                fiscal_year="FY2024-25",
                amount={"value": 8.0, "unit": "crore", "text": "Rs 8 crore"},
                evidence="too short", source_url="https://a.b/c", confidence="high",
            )


class TestMoneyCarriesItsUnit:
    """The crore bug, closed at the source. It has cost this codebase twice."""

    def test_the_source_wording_is_kept_beside_the_number(self):
        m = Money(value=1068.03, unit="crore", text="Rs 1,068.03 crore")
        assert m.inr == 10_680_300_000
        assert m.text == "Rs 1,068.03 crore"

    @pytest.mark.parametrize(
        ("value", "unit", "inr"),
        [(1.0, "crore", 10_000_000), (1.0, "lakh", 100_000), (4_270_000_000.0, "inr", 4_270_000_000)],
    )
    def test_each_unit_converts_once(self, value, unit, inr):
        assert Money(value=value, unit=unit, text="x").inr == inr

    def test_a_unit_cannot_be_left_to_inference(self):
        # This is the whole point: the old code read "Rs 1,068.03 crore" as
        # 1068.03 because nothing forced the scale to be stated.
        with pytest.raises(ValidationError):
            Money(value=1068.03, text="Rs 1,068.03 crore")

    def test_an_unknown_unit_is_refused(self):
        with pytest.raises(ValidationError):
            Money(value=5, unit="million", text="5 million")


class TestFindingsRefuseContradictions:
    def test_a_row_is_a_project_or_an_aggregate_but_not_both(self):
        with pytest.raises(ValidationError, match="aggregate"):
            CsrSpendFinding(
                fiscal_year="FY2024-25", project_name="Thalassemia Bal Sewa Yojana",
                project_count=12, amount={"value": 8.0, "unit": "crore", "text": "Rs 8 crore"},
                evidence="The company spent Rs 8 crore across 12 education projects in FY2024-25.",
                source_url="https://a.b/c", confidence="high",
            )

    def test_a_metric_with_no_number_is_not_a_metric(self):
        with pytest.raises(ValidationError, match="neither a value nor a target"):
            MetricFinding(
                name="beneficiaries",
                evidence="The programme reached communities across the district last year.",
                source_url="https://a.b/c", confidence="high",
            )

    def test_a_district_cannot_float_without_its_state(self):
        # "Barpeta" alone cannot be resolved to a locations row; with Assam it can.
        with pytest.raises(ValidationError):
            FootprintFinding(
                fiscal_year="FY2024-25", district="Barpeta",
                evidence="The programme ran in Barpeta district during the year under review.",
                source_url="https://a.b/c", confidence="high",
            )


class TestOldFindingsAreNotPromoted:
    async def test_a_v1_row_is_reported_rather_than_guessed_at(self):
        row = {
            "slug": "acme", "entity_name": "Acme Ltd", "canonical_name": None,
            "entity_kind": "funder", "researched_at": NOW, "schema_version": 1,
            "findings": [{"concept": "csr_year", "label": "FY2024-25 spent", "value": "427",
                          "source_url": "https://a.b/c", "evidence": "x" * 20,
                          "confidence": "high"}],
        }
        report = await promote(None, row)
        assert report["funder"] is None
        assert any("Re-run the research" in r for r in report["reasons"])
        assert SCHEMA_VERSION == 2


class TestOneConversionTable:
    def test_a_stored_money_finding_converts_through_the_same_table(self):
        # The unit table lived in three places at one point, which is how the
        # crore bug came back. to_inr is the only reader of it now.
        stored = Money(value=94.18, unit="crore", text="Rs 94.18 crore").model_dump(mode="json")
        assert to_inr(stored) == Money(value=94.18, unit="crore", text="x").inr

    @pytest.mark.parametrize("bad", [None, {}, {"value": 5, "unit": "million"}])
    def test_an_unreadable_amount_is_none_not_a_guess(self, bad):
        assert to_inr(bad) is None


class TestTheSummaryCannotUnderreport:
    def test_fact_count_is_required(self):
        with pytest.raises(ValidationError):
            ResearchSummary(slug="acme", entity_name="Acme Ltd", status="complete")


class TestPlaceNamesResolveOrAreRefused:
    """A state list is closed and a district list is not, so they differ."""

    @pytest.mark.parametrize(
        ("printed", "canonical"),
        [
            ("Assam", "Assam"), ("assam", "Assam"), ("ASSAM", "Assam"),
            # Names annual reports still print years after they changed.
            ("Orissa", "Odisha"), ("Pondicherry", "Puducherry"), ("Uttaranchal", "Uttarakhand"),
            ("NCT of Delhi", "Delhi"), ("Jammu & Kashmir", "Jammu and Kashmir"),
            ("Tamilnadu", "Tamil Nadu"), ("Assam State", "Assam"),
        ],
    )
    def test_one_spelling_per_state(self, printed, canonical):
        assert canonical_state(printed) == canonical

    @pytest.mark.parametrize("not_a_state", ["Barpeta", "Atlantis", "Northeast", "Assam Pradesh"])
    def test_anything_else_is_refused_rather_than_created(self, not_a_state):
        # A typo that becomes a state row is wrong for good, and nothing in the
        # schema would ever flag it.
        assert canonical_state(not_a_state) is None

    def test_there_are_thirty_six_states_and_union_territories(self):
        assert len(_STATES) == 36


class TestTheWriterSideRecords:
    """Seven new record types, all refusing what the writer cannot store."""

    def base(self, **kw):
        return {"funder_name": "Oil India Limited", **prov(), **kw}

    def test_a_market_is_not_a_funder_on_any_of_them(self):
        for model, extra in (
            (FunderCsrSpendRecord, {"fiscal_year": "FY2024-25", "amount": 1.0}),
            (FunderFootprintRecord, {"fiscal_year": "FY2024-25", "state": "Assam"}),
            (FunderPartnerRecord, {"fiscal_year": "FY2024-25", "partner_name": "Harsha Trust"}),
            (ProgramRecord, {"name": "Rural Health"}),
            (MetricRecord, {"name": "beneficiaries"}),
            (ContactRecord, {"name": "A. Borgohain"}),
        ):
            with pytest.raises(ValidationError, match="group of companies"):
                model(**{**self.base(funder_name="NSE-listed companies"), **extra})

    def test_fiscal_year_format_is_enforced_on_every_yearly_record(self):
        for model, extra in (
            (FunderCsrSpendRecord, {"amount": 1.0}),
            (FunderFootprintRecord, {"state": "Assam"}),
            (FunderPartnerRecord, {"partner_name": "Harsha Trust"}),
        ):
            with pytest.raises(ValidationError, match="FY2023-24"):
                model(**{**self.base(fiscal_year="FY25"), **extra})

    def test_an_amount_is_inr_and_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            FunderCsrSpendRecord(**self.base(fiscal_year="FY2024-25", amount=-1.0))


class TestPromotionCoversEveryConceptWithAWriter:
    def test_only_grant_is_left_out(self):
        # Eleven of twelve. grants.org_id is NOT NULL and orgs has no writer.
        assert set(CONCEPT_TABLES) - set(PROMOTABLE) == {"grant"}

    def test_programmes_are_written_before_anything_that_names_one(self):
        # csr_spend, footprint, partner and metric all resolve program_name to
        # a program_id, so a programme written after them would leave nulls.
        assert "program" not in WRITE_ORDER
        assert {"csr_spend", "footprint", "partner", "metric"} <= set(WRITE_ORDER)


class TestTheCatalogWriterCannotResearch:
    """The second subagent exists to check the write, not to add to it."""

    def test_it_holds_no_research_tools(self):
        names = {t.name for t in CATALOG_WRITER["tools"]}
        assert names == {"promote_research", "funder_dossier"}
        # No search, no fetch, no save: every value it writes came out of a
        # saved research row through fixed SQL.
        assert not names & {"search_public_sources", "read_page", "fetch_document",
                            "read_document_pages", "save_research"}

    def test_it_runs_in_its_own_context(self):
        assert CATALOG_WRITER["mode"] == "isolated"
        assert CATALOG_WRITER["response_format"] is PromotionReport

    def test_both_subagents_are_registered(self):
        # A subagent defined and not passed to create_deep_agent is a subagent
        # the model cannot launch — the same bug plan_import had.
        import inspect

        from app.ingest import agent as agent_module

        source = inspect.getsource(agent_module.build_ingest_agent)
        assert "ENTITY_RESEARCHER" in source and "CATALOG_WRITER" in source

    def test_the_instructions_tell_the_main_agent_to_launch_it(self):
        from app.ingest.agent import INSTRUCTIONS

        assert "catalog-writer" in INSTRUCTIONS

    def test_a_report_must_say_how_many_rows_it_wrote(self):
        with pytest.raises(ValidationError):
            PromotionReport(slug="acme")

    def test_nothing_written_is_a_valid_report_when_it_says_why(self):
        report = PromotionReport(
            slug="the-ant", rows_written=0,
            held_back=["researched as an organisation, not a funder"],
        )
        assert report.rows_written == 0 and report.held_back


class TestSavingCannotQuietlyShrinkAResult:
    """save_research upserts on (slug, date). A short re-run replacing a long
    one is how fifteen findings were lost; it now has to be deliberate."""

    def test_the_tool_takes_an_explicit_replace_flag(self):
        assert "replace" in save_research.args_schema.model_fields

    def test_the_refusal_explains_itself(self):
        # @tool wraps the function, so read the module rather than the object.
        from app.ingest.tools import research_tools

        source = inspect.getsource(research_tools)
        assert "REFUSED" in source and "replace=true" in source

    def test_the_docstring_says_what_replace_costs(self):
        assert "overwrite" in (save_research.description or "").lower()


class TestNothingResearchedIsSilentlyDropped:
    """A finding field with no record field is a fact that gets found,
    evidenced, saved — and thrown away on promotion without a word.

    Seven were: five of the ten statutory CSR items, the parent-company link
    and section_135_bound. That is the "pulled the information but nothing got
    saved" complaint in miniature, and nothing in the code would have said so.
    """

    EVIDENCE = frozenset({"concept", "evidence", "source_url", "source_name", "confidence", "basis"})

    @pytest.mark.parametrize("concept", sorted(CONCEPT_TABLES))
    def test_every_finding_field_reaches_a_record(self, concept):
        fields = set(FINDING_MODELS[concept].model_fields) - self.EVIDENCE
        record = CONCEPT_RECORDS.get(concept)
        carried = set(record.model_fields) if record else set()
        excused = set(NOT_WRITTEN.get(concept, {}))
        dropped = sorted(
            f for f in fields
            if RENAMED.get((concept, f), f) not in carried and f not in excused
        )
        assert not dropped, (
            f"{concept}: researched and never written — {dropped}. Add the field to its "
            f"record and writer, or name it in promote.NOT_WRITTEN with a reason."
        )

    def test_the_excuses_are_reasons_not_labels(self):
        for concept, fields in NOT_WRITTEN.items():
            for field, reason in fields.items():
                assert len(reason) > 12, f"{concept}.{field}: {reason!r} explains nothing"

    def test_nothing_is_excused_that_is_actually_written(self):
        # An excuse left behind after the field was wired up would hide the
        # next real drop on that concept.
        for concept, fields in NOT_WRITTEN.items():
            record = CONCEPT_RECORDS.get(concept)
            if record is None:
                continue
            stale = sorted(set(fields) & set(record.model_fields))
            assert not stale, f"{concept}: {stale} are written now — drop the NOT_WRITTEN entry"

    def test_all_ten_statutory_items_are_carried(self):
        items = {
            "average_net_profit", "prescribed_csr", "spent_on_projects", "admin_overheads",
            "impact_assessment_cost", "total_spent", "unspent_transferred", "excess_spent",
            "impact_assessment_done", "section_135_applicable",
        }
        assert items <= set(FunderCsrYearRecord.model_fields)
        assert items <= set(CSR_YEAR_UPDATABLE)


class TestAParentIsLinkedOnlyWhenTheMatcherWouldMerge:
    def test_only_the_merging_methods_count(self):
        # Match.resolved happens to be False for a trigram hit because its
        # funder_id is None. Relying on that made the policy accidental.
        assert set(MERGEABLE) == {"identifier", "exact", "alias", "boilerplate"}
        assert "trigram" not in MERGEABLE
        assert "none" not in MERGEABLE


class TestScheduleVIIIsAShelfNotAGuess:
    """A closed statutory list is safe to normalise against; a funder's own
    wording is not. Anything that does not place leaves csr_sector_id NULL."""

    @pytest.mark.parametrize(
        ("theme", "slug"),
        [
            ("Healthcare", "csr-hunger-poverty-health"),
            ("Education & Skilling", "csr-education-and-livelihoods"),
            ("Swachh Bharat sanitation drive", "csr-hunger-poverty-health"),
            ("Women empowerment", "csr-gender-equality-and-inequality"),
            ("Tree plantation", "csr-environment-and-animal-welfare"),
            ("Rural Development", "csr-rural-development"),
            ("Disaster relief", "csr-disaster-management"),
        ],
    )
    def test_a_recognisable_theme_is_placed(self, theme, slug):
        assert clause_for(theme) == slug

    @pytest.mark.parametrize("theme", ["Building Human Capital", "Project Unnati", "", None])
    def test_anything_needing_interpretation_is_left_alone(self, theme):
        # "Building Human Capital" is not Education until a person decides so.
        assert clause_for(theme) is None

    def test_skilling_reaches_education_before_rural_reaches_rural_development(self):
        # Ordering in CLAUSES is load-bearing: many themes mention "rural".
        assert clause_for("rural skill development centre") == "csr-education-and-livelihoods"


class TestOnlySharedMailboxesAreRecorded:
    def contact(self, **kw):
        return ContactFinding(
            name="R. Sharma", kind="grants",
            evidence="The CSR page lists this address for partnership enquiries from NGOs.",
            source_url="https://a.b/c", confidence="high", **kw,
        )

    @pytest.mark.parametrize(
        "email",
        # An allowlist of role words would have refused the last two, which is
        # most of what a fundraiser actually wants.
        ["csr@sbifoundation.in", "grants@itc.in", "csrhelpdesk@itc.in", "youthforindia@sbi.co.in"],
    )
    def test_a_shared_mailbox_is_kept(self, email):
        assert self.contact(email=email, is_role_mailbox=True).email == email

    @pytest.mark.parametrize("email", ["r.sharma@sbi.co.in", "rsharma@sbi.co.in", "sharma@x.org"])
    def test_an_individuals_address_is_refused_even_when_attested(self, email):
        with pytest.raises(ValidationError, match="personal address"):
            self.contact(email=email, is_role_mailbox=True)

    def test_an_address_with_no_attestation_is_refused(self):
        with pytest.raises(ValidationError, match="shared mailbox"):
            self.contact(email="csr@sbifoundation.in")

    def test_no_email_is_always_fine(self):
        assert self.contact().email is None


class TestRfpIsNowAConcept:
    def test_it_has_a_table_a_model_and_a_writer(self):
        assert CONCEPT_TABLES["rfp"] == "rfps"
        assert "rfp" in FINDING_MODELS
        assert "rfp" in PROMOTABLE
        assert "rfp" in WRITE_ORDER

    def test_the_grant_band_cannot_be_inverted(self):
        with pytest.raises(ValidationError, match="inverted"):
            RfpRecord(
                funder_name="SBI Foundation", title="A call", amount_min=100.0, amount_max=10.0,
                source_url="https://a.b/c", source_name="x", fetched_at=NOW,
            )

    def test_eligibility_survives_as_separate_lines(self):
        rec = RfpRecord(
            funder_name="SBI Foundation", title="Youth for India 2026",
            eligibility=["80G registration", "3 years of audited accounts"],
            source_url="https://a.b/c", source_name="x", fetched_at=NOW,
        )
        assert len(rec.eligibility) == 2


class TestPromotingTwiceChangesNothing:
    """Re-promotion used to churn six rows a run with no duplicate to show for
    it: two findings resolving to one row, and a float artifact."""

    def test_a_crore_amount_is_a_whole_number_of_rupees(self):
        # 4.73 * 10_000_000 is 47300000.00000001 in binary floating point.
        assert Money(value=4.73, unit="crore", text="Rs 4.73 crore").inr == 47_300_000
        assert to_inr({"value": 4.73, "unit": "crore", "text": "x"}) == 47_300_000

    def test_the_diff_tolerance_scales_with_the_amount(self):
        # An absolute 1e-9 epsilon is below float precision at crore scale, so
        # every comparison read as a change.
        assert _diff({"amount": 47_300_000}, {"amount": 47300000.00000001}) == {}
        assert "amount" in _diff({"amount": 47_300_000}, {"amount": 47_400_000})

    def test_two_findings_on_one_row_are_distinguished(self):
        # Distinct findings can still resolve to one row: two sector wordings
        # under the same Schedule VII clause, or two unresolved programme names
        # that are both a NULL program_id.
        spend = CsrSpendFinding(
            fiscal_year="FY2024-25", sector="Healthcare",
            amount={"value": 1.0, "unit": "crore", "text": "Rs 1 crore"},
            evidence="The company spent Rs 1 crore on healthcare during the year.",
            source_url="https://a.b/c", confidence="high",
        )
        first = _row_identity("csr_spend", spend, None, None, None, 7)
        same = _row_identity("csr_spend", spend, None, None, None, 7)
        other = _row_identity("csr_spend", spend, None, None, None, 9)
        assert first == same
        assert first != other


class TestJsonbColumnsCompareByValue:
    def test_a_jsonb_round_trip_is_not_a_change(self):
        # Postgres returns jsonb as a dict; the proposed value is the JSON
        # string about to be sent. Comparing them directly made every re-run
        # of an RFP look like an edit.
        stored = {"requirements": ["Registered under 80G"]}
        proposed = '{"requirements": ["Registered under 80G"]}'
        assert _diff({"eligibility": stored}, {"eligibility": proposed}) == {}

    def test_a_real_jsonb_change_is_still_seen(self):
        assert "eligibility" in _diff(
            {"eligibility": {"requirements": ["80G"]}},
            {"eligibility": '{"requirements": ["12A"]}'},
        )
