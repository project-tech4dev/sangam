"""The research judge: a cheap model scores a saved research to Langfuse and never touches the run."""

from __future__ import annotations

import json

import pytest

from app.ingest.research import draft, judge
from app.ingest.research.judge import ResearchJudge, ResearchQuality, judge_input
from app.ingest.research.source_guards import PRIVATE_SOURCE_DOMAIN

PUBLIC = "https://acme.org/annual-report"
SAVED = {"slug": "acme-foundation", "entity_kind": "funder", "status": "partial", "fact_count": 2}


def finding(url: str = PUBLIC, evidence: str = "Acme spent Rs 12 crore on CSR in FY2023-24.") -> dict:
    return {"concept": "csr_year", "fiscal_year": "FY2023-24", "amount_inr": 120000000, "evidence": evidence,
            "source_url": url, "confidence": "high", "basis": "stated", "notes": None}


QUALITY = ResearchQuality(correctness=4, completeness=3, relevance=5, consistency=5, source_quality=2,
                          notes="csr_year FY2023-24: a news aggregator, not the annual report")


class Model:
    def __init__(self, answer):
        self.answer, self.asked, self.method = answer, [], None

    def with_structured_output(self, schema, method=None):
        self.method = method
        return self

    async def ainvoke(self, prompt):
        self.asked.append(prompt)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


@pytest.fixture
def scores(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(judge, "score_answer", lambda name, value, comment=None, metadata=None:
                        sent.append((name, value, comment, metadata)))
    return sent


class TestWhatTheJudgeReads:
    def test_public_findings_and_gaps_with_quotes_cut_and_empties_dropped(self):
        current = draft.Draft(findings=[finding(evidence="x" * 1000)], gaps=[{"concept": "rfp", "reason": "not_stated"}])
        got = json.loads(judge_input(current, ["csr_year"]))
        (f,) = got["findings"]
        assert len(f["quote"]) == judge.QUOTE_CHARS and "evidence" not in f and "notes" not in f
        assert got["goals"] == ["csr_year"] and got["gaps"][0]["concept"] == "rfp"

    def test_a_private_quote_never_leaves(self):
        private = finding(url=f"https://{PRIVATE_SOURCE_DOMAIN}/grants.xlsx#Sheet1!B4", evidence="Confidential cell")
        assert judge_input(draft.Draft(findings=[private]), []) is None
        got = judge_input(draft.Draft(findings=[private, finding()]), [])
        assert "Confidential" not in got and PUBLIC in got

    def test_a_large_save_is_capped(self):
        many = [finding(url=f"{PUBLIC}/{i}") for i in range(judge.MAX_FINDINGS + 5)]
        assert len(json.loads(judge_input(draft.Draft(findings=many), []))["findings"]) == judge.MAX_FINDINGS


class TestTheJudgeScores:
    async def test_each_dimension_is_one_score_for_the_slug(self, scores):
        model = Model(QUALITY)
        with draft.drafting() as current:
            current.findings, current.saved, current.goals = [finding()], SAVED, ["csr_year"]
            assert await ResearchJudge(model).aafter_agent({}, None) is None
        assert model.method == "json_schema" and "acme-foundation" in model.asked[0]
        assert [(n, v) for n, v, _, _ in scores] == [
            ("research_correctness", 4), ("research_completeness", 3), ("research_relevance", 5),
            ("research_consistency", 5), ("research_source_quality", 2)]
        assert all(c == QUALITY.notes and m == {"slug": "acme-foundation"} for _, _, c, m in scores)

    @pytest.mark.parametrize("setup", ["no_run", "not_saved", "only_private"])
    async def test_nothing_saved_or_nothing_public_is_not_judged(self, scores, setup):
        model = Model(QUALITY)
        if setup == "no_run":
            await ResearchJudge(model).aafter_agent({}, None)
        else:
            with draft.drafting() as current:
                if setup == "only_private":
                    current.saved = SAVED
                    current.findings = [finding(url=f"https://{PRIVATE_SOURCE_DOMAIN}/a.xlsx#S!A1")]
                await ResearchJudge(model).aafter_agent({}, None)
        assert model.asked == [] and scores == []

    async def test_a_failing_judge_is_logged_and_the_run_goes_on(self, scores, caplog):
        with draft.drafting() as current:
            current.findings, current.saved = [finding()], SAVED
            assert await ResearchJudge(Model(TimeoutError("slow"))).aafter_agent({}, None) is None
        assert scores == [] and "research judge failed for acme-foundation" in caplog.text
