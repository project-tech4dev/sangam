"""save_research payloads as researchers really send them, through ToolNode and SaveRefusal.

Each case is the shape of a refusal seen in a real Import run (trace 9b31e258…, 2026-10-11),
with synthetic text in place of the staff-sheet cells it quoted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.ingest.middleware import REFUSAL_LINES, SaveRefusal, parse_payload
from app.ingest.research_records import EntityResearch
from app.ingest.tools.research_tools import save_research

SAVED: list[EntityResearch] = []


def _stand_in(findings: EntityResearch, replace: bool = False) -> str:
    SAVED.append(findings)
    return "saved"


# save_research's own argument schema, minus the database: validation is what is under test.
TOOL = StructuredTool.from_function(
    func=_stand_in, name="save_research", description=save_research.description,
    args_schema=save_research.args_schema,
)
URL = "https://example.org/csr-report-2024-25.pdf"
EVIDENCE = "The company spent Rs 6.74 crore on sports scholarships in FY2023-24."


def spend(**over) -> dict:
    return {
        "concept": "csr_spend", "fiscal_year": "FY2023-24", "project_name": "Sports scholarships for 250 athletes",
        "sector": "Training to promote sports", "amount": {"value": 6.74, "unit": "crore", "text": "Rs 6.74 crore"},
        "domain": "others", "theme": "sports-development", "classified_by": "project_name",
        "confidence": "medium", "source_url": URL, "evidence": EVIDENCE, **over,
    }


def programme(**over) -> dict:
    return {
        "concept": "programme_spend", "fiscal_year": "FY2024-25", "program_name": "Disaster management",
        "amount": {"value": 83.86, "unit": "crore", "text": "Rs 83.86 crore"}, "domain": "others",
        "theme": "disaster", "classified_by": "report", "confidence": "medium", "source_url": URL,
        "evidence": "Disaster management | 83.86 | 9.03% of the year's CSR spend", **over,
    }


def partner(**over) -> dict:
    return {
        "concept": "partner", "fiscal_year": "FY2025-26", "partner_name": "Example Water Trust",
        "project_name": "Spring revival in Udalguri", "start_date": "2026-01-01", "end_date": "2027-12-31",
        "relationship_status": "active", "confidence": "medium", "source_url": URL,
        "evidence": "Spring revival in Udalguri, Jan 2026 - Dec 2027 (ongoing), with Example Water Trust", **over,
    }


def guideline(**over) -> dict:
    return {
        "concept": "eligibility_guideline", "title": "Partner selection criteria",
        "own_bar": "Have a track record of a minimum of 3 years of service in the sector",
        "confidence": "low", "source_url": URL,
        "evidence": "Applicants must have a track record of a minimum of 3 years of service.", **over,
    }


def research(*findings: dict, **over) -> dict:
    return {
        "entity_name": "Example Foundation", "entity_kind": "funder", "status": "partial",
        "stopped_reason": "Stopped at the reading limit. Unread: the FY2024-25 annual report.",
        "summary": "Example Foundation funds sports, disaster relief and water projects in Assam.",
        "findings": list(findings) or [spend(classification_note="project 'Sports scholarships'")], **over,
    }


def graph(**wrap):
    # ToolNode needs a graph's runtime around it; one node is enough.
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([TOOL], **wrap))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def ask(findings, **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "save_research", "id": "c1", "args": {"findings": findings, **args}}])


def call(findings, **args) -> list[ToolMessage]:
    out = graph(wrap_tool_call=SaveRefusal().wrap_tool_call).invoke({"messages": [ask(findings, **args)]})
    return out["messages"][1:]


def saved(findings, **args) -> EntityResearch:
    SAVED.clear()
    [out] = call(findings, **args)
    assert out.status != "error", out.content
    [result] = SAVED
    return result


def refused(findings, **args) -> str:
    SAVED.clear()
    [out] = call(findings, **args)
    assert out.status == "error" and not SAVED, out.content
    assert out.content.startswith("Error invoking tool 'save_research': refused, nothing saved."), out.content
    return out.content


class TestAPayloadSentAsAString:
    def test_valid_json_is_parsed_and_saved(self):
        assert saved(json.dumps(research())).entity_name == "Example Foundation"

    @pytest.mark.parametrize("tail", ["}", "}}", "]}", "}\n", "  } "])
    def test_surplus_closing_brackets_are_forgiven(self, tail):
        # Seen twice: a 32 KB payload, valid but for one '}' too many at the end.
        assert saved(json.dumps(research()) + tail).status == "partial"

    def test_text_after_the_object_is_not_forgiven(self):
        assert "not valid JSON" in refused(json.dumps(research()) + " and that is everything")

    def test_a_broken_string_says_where_it_broke_and_to_send_an_object(self):
        # Seen once: a quote dropped mid-URL, "source_url":"https":"//…".
        text = json.dumps(research()).replace('"source_url": "https://', '"source_url": "https": "//', 1)
        msg = refused(text)
        assert "not valid JSON" in msg and "at character" in msg and "near" in msg
        assert "as an object, not a string" in msg
        assert len(msg) < 600, "the refusal must not echo the payload"

    def test_a_string_that_is_not_an_object_is_refused(self):
        assert "not as an object" in refused(json.dumps([research()]))

    def test_parse_payload_never_guesses(self):
        assert parse_payload('{"a": 1}}') == {"a": 1}
        assert parse_payload('{"a": 1} {"b": 2}') is None
        assert parse_payload('{"a": ') is None
        assert parse_payload("[1, 2]") is None


class TestTheStatusAndItsReason:
    @pytest.mark.parametrize("status", ["partial", "wrong_entity"])
    def test_a_missing_stopped_reason_is_refused_in_one_line(self, status):
        msg = refused(research(status=status, stopped_reason=None))
        assert f"- top level: status {status!r} needs a stopped_reason saying why" in msg

    def test_a_missing_stopped_reason_with_many_findings_still_lists_only_the_fix(self):
        msg = refused(research(*[spend(classification_note="project 'x'")] * 49, stopped_reason=None))
        assert msg.count("\n- ") == 1 and "Fix these 1" in msg

    def test_complete_needs_no_reason(self):
        assert saved(research(status="complete", stopped_reason=None)).status == "complete"


class TestAThemeNamesWhatItRestsOn:
    def test_a_project_line_quotes_its_project_name(self):
        [f] = saved(research(spend())).findings
        assert f.classification_note == "project 'Sports scholarships for 250 athletes'"

    def test_a_filed_sector_line_quotes_its_sector(self):
        [f] = saved(research(spend(classified_by="filed_sector"))).findings
        assert f.classification_note == "filed under 'Training to promote sports'"

    def test_a_programme_line_quotes_its_programme(self):
        [f] = saved(research(programme())).findings
        assert f.classification_note == "programme 'Disaster management'"

    def test_a_note_given_is_kept(self):
        [f] = saved(research(spend(classification_note="annexure row 12: sports"))).findings
        assert f.classification_note == "annexure row 12: sports"

    def test_no_theme_needs_no_note(self):
        [f] = saved(research(spend(theme=None, project_name=None))).findings
        assert f.classification_note is None

    @pytest.mark.parametrize("finding", [
        spend(classified_by="partner"),                 # no partner_name to quote
        spend(project_name="  ", classified_by="project_name"),
        programme(classified_by="project_name"),        # programme_spend has no project_name
    ])
    def test_with_nothing_to_quote_it_is_refused(self, finding):
        assert "a theme needs a classification_note" in refused(research(finding))

    def test_both_failing_lines_of_the_real_run_now_save(self):
        assert len(saved(research(spend(), programme())).findings) == 2


class TestAGrantSitsInTheYearItStarted:
    def test_the_start_year_is_accepted(self):
        [f] = saved(research(partner())).findings
        assert f.fiscal_year == "FY2025-26"

    def test_the_last_year_of_the_range_is_refused_naming_the_right_one(self):
        msg = refused(research(partner(fiscal_year="FY2027-28")))
        assert "sits in the fiscal year it started: FY2025-26, not FY2027-28" in msg

    def test_a_range_without_dates_may_sit_on_any_year(self):
        [f] = saved(research(partner(fiscal_year="FY2027-28", start_date=None, end_date=None))).findings
        assert f.fiscal_year == "FY2027-28"

    def test_the_researcher_prompt_says_the_start_year_everywhere(self):
        prompt = (Path(__file__).parents[1] / "app/ingest/prompts/entity_researcher.md").read_text()
        assert "**last** fiscal year" not in prompt
        assert prompt.count("in the fiscal year it **started**") + prompt.count("in the fiscal year it started") >= 2


class TestANullUnderAMissingKey:
    def test_a_null_extra_on_a_finding_is_dropped(self):
        # Seen once: eligibility_guideline has no `notes`, and the researcher sent notes=null.
        [f] = saved(research(guideline(notes=None))).findings
        assert not hasattr(f, "notes")

    def test_a_null_extra_at_the_top_is_dropped(self):
        assert saved(research(notes=None)).entity_name == "Example Foundation"

    def test_a_value_under_a_missing_key_is_still_refused(self):
        msg = refused(research(guideline(notes="third-party summary")))
        assert "`notes` is not a field of eligibility_guideline" in msg

    def test_a_null_on_a_real_field_still_means_null(self):
        [f] = saved(research(spend(classification_note="project 'x'", district=None))).findings
        assert f.district is None


class TestTheRefusal:
    def test_it_numbers_each_problem_by_finding(self):
        msg = refused(research(spend(classified_by="partner"), partner(fiscal_year="FY2027-28")))
        assert "Fix these 2" in msg
        assert "- finding 0 (csr_spend 'Sports scholarships for 250 athletes')" in msg
        assert "- finding 1 (partner 'Example Water Trust') fiscal_year" not in msg
        assert "- finding 1 (partner 'Example Water Trust'): a line with a start date" in msg

    def test_it_is_capped(self):
        bad = [spend(classified_by="partner")] * (REFUSAL_LINES + 5)
        msg = refused(research(*bad))
        assert msg.count("\n- ") == REFUSAL_LINES + 1 and "and 5 more of the same kinds" in msg

    def test_replace_inside_findings_points_at_the_argument(self):
        assert "`replace` is an argument beside `findings`" in refused(research(replace=True))

    def test_a_payload_with_no_problems_reaches_the_tool_untouched(self):
        payload = research(spend(classification_note="project 'x'"))
        before = copy.deepcopy(payload)
        saved(payload, replace=True)
        assert payload == before

    async def test_the_async_path_does_the_same(self):
        SAVED.clear()
        g = graph(awrap_tool_call=SaveRefusal().awrap_tool_call)
        [out] = (await g.ainvoke({"messages": [ask(json.dumps(research()) + "}")]}))["messages"][1:]
        assert out.status != "error" and len(SAVED) == 1


class TestWhatTheModelIsTold:
    """The model reads the tool's JSON schema, not the validator, so each rule is stated there."""

    @pytest.fixture
    def schema(self) -> str:
        return json.dumps(save_research.tool_call_schema.model_json_schema())

    def test_stopped_reason_says_when_it_is_required(self, schema):
        assert "REQUIRED when status is 'partial' or 'wrong_entity'" in schema

    def test_classification_note_says_it_is_required_with_a_theme(self, schema):
        assert "REQUIRED with a theme" in schema

    def test_a_multi_year_grant_says_its_start_year(self, schema):
        assert "in the fiscal_year it started" in schema
