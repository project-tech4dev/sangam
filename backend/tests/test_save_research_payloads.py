"""Findings as researchers really send them, through record_findings and the draft it keeps.

Each case is the shape of a refusal seen in a real Import run (traces 9b31e258…, 1b117e6e, c2b6973d), with
synthetic text in place of the staff-sheet cells it quoted. Langfuse cut the real inputs at ~4,000 characters.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingest.middleware import parse_payload
from app.ingest.research import draft
from app.ingest.research.findings import EntityResearch
from app.ingest.tools.research_tools import record_findings, save_research

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


def contact(**over) -> dict:
    return {
        "concept": "contact", "name": "ONGC Company Secretariat", "kind": "other",
        "email": "secretariat@ongc.co.in", "is_role_mailbox": True, "confidence": "medium", "source_url": URL,
        "evidence": "Shareholders may write to the Company Secretariat at secretariat@ongc.co.in.", **over,
    }


def gap(**over) -> dict:
    return {"concept": "metric", "reason": "not_stated", "detail": "No reach figures found.", **over}


def head(**over) -> dict:
    return {
        "entity_name": "Example Foundation", "entity_kind": "funder", "status": "partial",
        "stopped_reason": "Stopped at the reading limit. Unread: the FY2024-25 annual report.",
        "summary": "Example Foundation funds sports, disaster relief and water projects in Assam.", **over,
    }


def record(findings=None, gaps=None, unplaced=None, into: draft.Draft | None = None) -> tuple[draft.Draft, str]:
    current = into or draft.Draft()
    return current, draft.record(current, findings, gaps, unplaced)


def kept(*findings: dict, gaps=None) -> list[dict]:
    current, reply = record(list(findings), gaps)
    assert "Refused" not in reply, reply
    return current.findings


def refused(*findings: dict, gaps=None) -> str:
    current, reply = record(list(findings), gaps)
    assert "Refused" in reply and not current.findings, reply
    return reply


def whole(current: draft.Draft, **over) -> EntityResearch:
    return EntityResearch.model_validate({**head(**over), "findings": current.findings, "gaps": current.gaps})


def problems(current: draft.Draft, **over) -> str:
    with pytest.raises(ValidationError) as exc:
        whole(current, **over)
    return "\n".join(draft.problems(exc.value, current.findings))


class TestAListSentAsAString:
    def test_valid_json_is_parsed_and_kept(self):
        current, reply = record(json.dumps([spend()]))
        assert len(current.findings) == 1 and "Recorded 1 findings" in reply

    def test_one_object_is_a_list_of_one(self):
        assert len(record(spend())[0].findings) == 1

    @pytest.mark.parametrize("tail", ["]", "]}", "}\n", "  ] "])
    def test_surplus_closing_brackets_are_forgiven(self, tail):
        # Seen twice: a 32 KB payload, valid but for one '}' too many at the end.
        assert len(record(json.dumps([spend()]) + tail)[0].findings) == 1

    def test_text_after_the_list_is_not_forgiven(self):
        current, reply = record(json.dumps([spend()]) + " and that is everything")
        assert "findings: not valid JSON" in reply and not current.findings

    def test_a_number_is_refused(self):
        assert "expected a list of objects, got int" in record(7)[1]

    def test_parse_payload_never_guesses(self):
        assert parse_payload('{"a": 1}}') == {"a": 1}
        assert parse_payload('{"a": 1} {"b": 2}') is None
        assert parse_payload('{"a": ') is None
        assert parse_payload("[1, 2]") is None

    def test_a_url_split_at_its_colon_is_rejoined(self):
        # Seen in two runs in a row (IRCTC, 43 KB): "source_url":"https":"//…".
        text = json.dumps([spend()]).replace('"source_url": "https://', '"source_url":"https":"//', 1)
        [f] = record(text)[0].findings
        assert f["source_url"] == URL


class TestEachItemStandsAlone:
    def test_one_bad_finding_never_costs_the_good_ones(self):
        # c2b6973d step 12: two identity fields refused the whole 57-fact payload, which was written again.
        current, reply = record([spend(), spend(classified_by="partner"), programme()])
        assert len(current.findings) == 2
        assert "Refused 1; send only these again" in reply and "findings[1] (csr_spend" in reply

    def test_an_unknown_key_is_dropped_and_named_not_refused(self):
        # 1b117e6e: one empty `goals_note` refused a whole save and cost $1.32.
        [f] = kept(spend(goals_note=""))
        assert "goals_note" not in f
        assert "findings[0] `goals_note`" in record([spend(goals_note="")])[1]

    def test_an_unknown_concept_names_the_allowed_ones(self):
        assert "unknown concept 'sector'" in refused({"concept": "sector"})

    def test_a_non_object_is_refused(self):
        assert "findings[0]: not an object" in refused("x")

    def test_sending_a_fact_again_replaces_it(self):
        current, _ = record([spend()])
        record([spend(confidence="high")], into=current)
        [f] = current.findings
        assert f["confidence"] == "high"

    def test_the_same_fact_from_another_source_is_kept_beside_it(self):
        current, _ = record([spend(), spend(source_url="https://example.org/other.pdf")])
        assert len(current.findings) == 2

    def test_a_long_list_of_problems_is_cut_per_item(self):
        bad = {k: None for k in ("evidence", "source_url", "confidence", "fiscal_year", "amount", "sector")}
        reply = refused(spend(**bad))
        assert reply.split("findings[0]")[1].count(";") < draft.LINES_PER_ITEM

    def test_the_items_sent_are_not_changed(self):
        payload = [spend(classification_note="project 'x'", goals_note="")]
        before = copy.deepcopy(payload)
        record(payload)
        assert payload == before

    async def test_the_tool_records_into_the_open_run(self):
        with draft.drafting() as current:
            reply = await record_findings.ainvoke({"findings": [spend()], "gaps": [gap()]})
        assert "Recorded 1 findings, 1 gaps" in reply and len(current.gaps) == 1

    async def test_outside_a_run_it_says_so(self):
        assert "no research run is open" in await record_findings.ainvoke({"findings": [spend()]})


class TestTheStatusAndItsReason:
    @pytest.mark.parametrize("status", ["partial", "wrong_entity"])
    def test_a_missing_stopped_reason_is_named(self, status):
        current, _ = record([spend()])
        assert f"status {status!r} needs a stopped_reason saying why" in problems(
            current, status=status, stopped_reason=None)

    def test_complete_needs_no_reason(self):
        current, _ = record([spend()])
        assert whole(current, status="complete", stopped_reason=None).status == "complete"

    def test_a_problem_names_its_finding_not_an_index(self):
        current, _ = record([partner()])
        current.findings[0]["confidence"] = "certain"
        assert "finding (partner 'Example Water Trust') confidence" in problems(current)


class TestAThemeNamesWhatItRestsOn:
    def test_a_project_line_quotes_its_project_name(self):
        [f] = kept(spend())
        assert f["classification_note"] == "project 'Sports scholarships for 250 athletes'"

    def test_a_filed_sector_line_quotes_its_sector(self):
        [f] = kept(spend(classified_by="filed_sector"))
        assert f["classification_note"] == "filed under 'Training to promote sports'"

    def test_a_programme_line_quotes_its_programme(self):
        [f] = kept(programme())
        assert f["classification_note"] == "programme 'Disaster management'"

    def test_a_note_given_is_kept(self):
        [f] = kept(spend(classification_note="annexure row 12: sports"))
        assert f["classification_note"] == "annexure row 12: sports"

    def test_no_theme_needs_no_note(self):
        [f] = kept(spend(theme=None, project_name=None))
        assert f["classification_note"] is None

    @pytest.mark.parametrize("finding", [
        spend(classified_by="partner"),                 # no partner_name to quote
        spend(project_name="  ", classified_by="project_name"),
        programme(classified_by="project_name"),        # programme_spend has no project_name
    ])
    def test_with_nothing_to_quote_it_is_refused(self, finding):
        assert "a theme needs a classification_note" in refused(finding)

    def test_research_goals_carries_the_rule(self):
        # The tool's schema no longer describes each field, so research_goals prints what the columns cannot.
        src = (Path(__file__).parents[1] / "app/ingest/tools/catalog_tools.py").read_text()
        assert "v.description" in src


class TestAGrantSitsInTheYearItStarted:
    def test_the_start_year_is_accepted(self):
        [f] = kept(partner())
        assert f["fiscal_year"] == "FY2025-26"

    def test_the_last_year_of_the_range_is_refused_naming_the_right_one(self):
        assert "sits in the fiscal year it started: FY2025-26, not FY2027-28" in refused(partner(fiscal_year="FY2027-28"))

    def test_a_range_without_dates_may_sit_on_any_year(self):
        [f] = kept(partner(fiscal_year="FY2027-28", start_date=None, end_date=None))
        assert f["fiscal_year"] == "FY2027-28"

    def test_the_researcher_prompt_says_the_start_year_everywhere(self):
        prompt = (Path(__file__).parents[1] / "app/ingest/prompts/entity_researcher.md").read_text()
        assert "**last** fiscal year" not in prompt
        assert prompt.count("in the fiscal year it **started**") + prompt.count("in the fiscal year it started") >= 2


class TestANullUnderAMissingKey:
    def test_a_null_extra_on_a_finding_is_dropped(self):
        # Seen once: eligibility_guideline has no `notes`, and the researcher sent notes=null.
        [f] = kept(guideline(notes=None))
        assert "notes" not in f

    def test_a_null_on_a_real_field_still_means_null(self):
        [f] = kept(spend(district=None))
        assert f["district"] is None


class TestAYearOnAGapThatIsNotByYear:
    def test_the_year_moves_into_the_detail(self):
        current, _ = record(gaps=[gap(fiscal_year="FY2025-26")])
        [g] = current.gaps
        assert (g["fiscal_year"], g["detail"]) == (None, "No reach figures found. (FY2025-26)")

    def test_a_bad_year_on_a_yearly_concept_is_refused(self):
        current, reply = record(gaps=[gap(concept="csr_spend", fiscal_year="2025")])
        assert "must look like 'FY2023-24'" in reply and not current.gaps

    def test_a_not_reached_gap_is_a_reason_the_save_accepts(self):
        # The old grader failed this run for not_reached, which the Gap type and the prompt both allow.
        current, _ = record(gaps=[gap(reason="not_reached", detail="Unread: the FY2024-25 annual report.")])
        assert current.gaps[0]["reason"] == "not_reached"


class TestAnOfficesMailbox:
    def test_an_office_named_contact_is_kept(self):
        assert kept(contact())[0]["email"]

    def test_a_persons_surname_in_the_address_is_still_refused(self):
        assert "from the contact's own name" in refused(contact(name="Rahul Sharma", email="rsharma@x.org"))


class TestTheStaffOnlyGapRule:
    def test_the_prompt_puts_it_under_its_own_concept(self):
        prompt = (Path(__file__).parents[1] / "app/ingest/prompts/entity_researcher.md").read_text()
        assert "under the concept it belongs to" in prompt


class TestWhatTheModelIsSent:
    def test_the_save_schema_no_longer_carries_the_findings(self):
        # The old schema was 67,852 characters, sent on every researcher call.
        schema = json.dumps(save_research.tool_call_schema.model_json_schema())
        assert "findings" not in save_research.tool_call_schema.model_fields and len(schema) < 3_000

    def test_stopped_reason_says_when_it_is_required(self):
        assert "REQUIRED for 'partial' and 'wrong_entity'" in save_research.description
