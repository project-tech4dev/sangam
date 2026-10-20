"""The research brief: one headline per concept, merging across runs, and the rendered page."""

from __future__ import annotations

import json

import pytest

from app.ingest import brief
from app.integrations import storage


def money(value, unit="crore", text=None):
    return {"value": value, "unit": unit, "text": text or f"{value} {unit}"}


@pytest.mark.parametrize("finding,expected", [
    ({"label": "Founded", "value": "1990"}, "Founded · 1990"),
    ({"concept": "identity", "name": "Acme", "funder_type": "csr", "founded_year": 1990, "parent_name": "Acme Ltd"},
     "Acme · csr · founded 1990 · part of Acme Ltd"),
    ({"concept": "identifier", "id_type": "cin", "id_value": "U123"}, "CIN U123"),
    ({"concept": "csr_year", "total_spent": money(2)}, "total spent ₹2.00 cr (2 crore)"),
    ({"concept": "csr_year"}, "recorded"),
    ({"concept": "csr_spend", "project_name": "Wells", "amount": money(5, "lakh"), "state": "Assam",
      "district": "Kamrup", "project_count": 3, "partner_name": "P", "domain": "health", "theme": "wash"},
     "Wells · ₹500,000 (5 lakh) · Kamrup, Assam · 3 projects · P · health/wash (inferred)"),
    ({"concept": "csr_spend"}, "aggregate"),
    ({"concept": "footprint", "name_as_printed": "NE", "program_name": "Prog"}, "NE · Prog"),
    ({"concept": "stated_geography", "state": "Assam", "role": "funds"}, "Assam · funds"),
    ({"concept": "partner", "partner_name": "P", "relationship_status": "current"}, "P · current"),
    ({"concept": "programme_spend", "program_name": "Prog", "domain": "health"},
     "Prog · the funder's own figure · health"),
    ({"concept": "program", "name": "Prog", "start_date": "2020", "end_date": "2022", "parent_name": "Big"},
     "Prog · 2020–2022 · under Big"),
    ({"concept": "grant", "recipient_name": "R", "title": "T", "status": "paid"}, "R · T · paid"),
    ({"concept": "metric", "name": "Girls", "value": 40, "unit": "people", "target": 10, "stage": "output"},
     "Girls · 40 · people · target 10 · output"),
    ({"concept": "contact", "name": "N", "role": "CEO"}, "N · CEO"),
    ({"concept": "document", "title": "AR", "doc_type": "annual_report", "as_of": "2024"}, "AR · annual_report · 2024"),
    ({"concept": "rfp", "title": "Call", "amount_min": money(1), "deadline": "2026-12-01", "status": "closed",
      "eligibility": ["a", "b"]}, "Call · ₹1.00 cr (1 crore) · closes 2026-12-01 · closed · 2 eligibility rules"),
    ({"concept": "eligibility_guideline", "title": "G", "not_stated": True}, "G · states no eligibility"),
    ({"concept": "eligibility_guideline", "title": "G", "own_bar": "3 years"}, "G · its own bar: 3 years"),
    ({"concept": "funder_eligibility", "kind": "own_bar", "criterion": "3 yrs"}, "its own bar · 3 yrs"),
    ({"concept": "org_identity", "name": "O", "registration_date": "2001", "parent_name": "X"},
     "O · registered 2001 · part of X"),
    ({"concept": "org_identifier", "id_type": "fcra", "application_ref": "A1", "status": "applied",
      "valid_until": "2027", "evidence_tier": "claimed", "source_type": "self"},
     "FCRA · application A1 · applied · valid until 2027 · claimed (self)"),
    ({"concept": "org_financials", "total_income": money(100, "inr"), "is_audited": False},
     "total income ₹100 (100 inr) · unaudited"),
    ({"concept": "org_financials"}, "recorded"),
    ({"concept": "org_location", "state": "Assam", "role": "works"}, "Assam · works"),
    ({"concept": "brand_new", "colour": "blue", "evidence": "x", "nothing": None}, "blue"),
])
def test_headline(finding, expected):
    assert brief.headline(finding) == expected


@pytest.mark.xfail(strict=True, reason="_join drops falsy bits, so the `is not None` guard cannot keep a 0 value")
def test_metric_value_zero_is_printed():
    f = {"concept": "metric", "name": "Girls enrolled", "value": 0, "unit": "girls"}
    assert brief.headline(f) == "Girls enrolled · 0 · girls"


def test_crore_and_money_fallbacks():
    assert brief._crore("n/a") == "n/a"
    assert brief._money({"value": 1, "unit": "usd", "text": "$1"}) is None


def test_fact_key_falls_back_to_headline_and_year():
    f = {"concept": "grant", "recipient_name": "R", "fiscal_year": "FY24"}
    assert brief.fact_key(f) == ("grant", "r", "fy24")
    assert brief.fact_key({"label": "X", "value": 1})[0] == "v1:x"


def test_merge_keeps_stronger_earlier_source_and_skips_wrong_entity():
    weak = {"concept": "identity", "name": "New", "confidence": "low"}
    strong = {"concept": "identity", "name": "Old", "confidence": "high", "evidence_tier": "evidenced"}
    rows = [{"findings": [strong]}, {"findings": json.dumps([weak])},
            {"status": "wrong_entity", "findings": [{"concept": "contact", "name": "Other org"}]}]
    assert brief.merge_findings(rows) == [strong]


def test_record_skips_a_broken_block():
    md = '<!-- fact {"a": 1} --> <!-- unplaced {"field": "x"} --> <!-- fact {broken} -->'
    assert brief.record(md) == ([{"a": 1}], [{"field": "x"}])


def test_block_escapes_double_dash():
    assert "--" not in brief._block("fact", {"v": "a -- b"})[5:-4]


def test_open_gaps():
    gaps = [{"concept": "csr_year", "fiscal_year": "FY23", "reason": "blocked", "detail": "403  from\nsite"},
            {"concept": "csr_year", "field": "total_spent", "reason": "odd", "detail": "x"},
            {"concept": "other", "reason": "not_stated", "detail": "x"}]
    assert brief._open_gaps(gaps, "csr_year", [{"fiscal_year": "FY23"}]) == ["- odd · total_spent: x"]
    assert brief._open_gaps(gaps, "csr_year", []) == ["- Could not read · FY23: 403 from site",
                                                     "- odd · total_spent: x"]


SRC = "https://acme.org/report.pdf"
PRIVATE = "https://staff-sources.sangam.invalid/abc"


def ev(**f):
    return {"evidence": "The report says so plainly.", "source_url": SRC, "source_name": "Annual report",
            "confidence": "high", **f}


def row(**kw):
    base = {"slug": "acme", "canonical_name": "Acme Foundation", "entity_name": "acme", "entity_kind": "funder",
            "researched_on": "2026-10-01", "researched_at": "t1", "status": "complete", "stopped_reason": None,
            "summary": "Acme funds health.", "website": None, "goals": None, "schema_version": 2,
            "gaps": [], "not_found": [], "sources_read": [], "findings": []}
    return {**base, **kw}


class TestEntityMarkdown:
    def test_full_page(self):
        findings = [
            ev(concept="program", name="Swasthya", description="Clinics  in\nhills", themes=["skilling"],
               populations=["women"], lenses=["women_girls"], tag_note="from the report"),
            ev(concept="footprint", state="Assam", program_name="Swasthya", fiscal_year="FY24"),
            ev(concept="partner", partner_name="NGO A", program_name="swasthya", basis="inferred"),
            ev(concept="metric", name="Patients", value=100, program_name="Swasthya"),
            ev(concept="programme_spend", program_name="Swasthya", amount=money(2)),
            ev(concept="document", title="Annual report", doc_type="annual_report", summary="A  long\nsummary",
               page="p. 4"),
            ev(concept="grant", recipient_name="R"),  # a legacy concept still renders
        ]
        older = row(researched_on="2026-01-01", website="https://acme.org", schema_version=1,
                    findings=[ev(concept="contact", name="Old Contact", role="CEO")])
        newest = row(goals=json.dumps(["find the CSR policy"]), stopped_reason="out of pages",
                     findings=findings, not_found=["rfp", "mystery"],
                     gaps=[{"concept": "csr_year", "reason": "not_reached", "detail": "no time"}],
                     sources_read=[SRC, "https://acme.org/about", PRIVATE])
        states = {json.dumps(list(brief.fact_key(findings[1]))): {"state": "conflicts", "row": "funder:1",
                                                                   "reason": "Sangam  says\nKerala"},
                  json.dumps(list(brief.fact_key(findings[3]))): {"state": "written", "row": "metric:3"},
                  json.dumps(list(brief.fact_key(findings[5]))): {"state": "written", "documents": {SRC: [9, "ar"]}}}
        unplaced = [{"field": "motto", "value": "Do  good", "evidence": "It says so.", "source_url": SRC},
                    {"field": "secret", "value": "x", "evidence": "y", "source_url": PRIVATE}]
        md = brief.entity_markdown([newest, older], unplaced=unplaced, states=states)

        assert md.startswith("# Acme Foundation\n") and brief.STAMP in md
        assert "status **complete** · out of pages" in md and "Website: https://acme.org" in md
        assert "- find the CSR policy" in md and "earlier finding shape" in md
        assert "- Not reached · anything: no time" in md  # an empty section shows its gap
        assert "  - Description: Clinics in hills" in md and "  - Themes: Skilling for jobs & employment" in md
        assert "  - Where: Assam · Swasthya (FY24)" in md and "  - Funded by: NGO A · swasthya" in md
        assert "_inferred_" in md and "  - Summary: A long summary" in md
        assert "  - In Sangam: Sangam holds another value; a person decides · funder:1 · Sangam says Kerala" in md
        assert "## Not in Sangam yet" in md and "## Grants (saved before 0034)" in md
        assert "## Stated, but Sangam has no field for it" in md and "motto: Do good" in md and "secret" not in md
        assert "## Research runs" in md and "- 2026-01-01 · complete · 1 findings" in md
        assert "open calls for proposals, mystery." in md.split("## Looked for, not found")[1]
        assert f"- {SRC} · Annual report · annual_report · p. 4 · 8 facts · [documents:9]" in md
        assert "- https://acme.org/about · read; no fact cites it" in md and PRIVATE not in md

    def test_private_findings_hide_the_summary(self):
        md = brief.entity_markdown(row(findings=[ev(concept="identity", name="A", source_url=PRIVATE)],
                                       status="wrong_entity", gaps=json.dumps([{"concept": "identity"}])))
        assert brief.PRIVATE_NOTE in md and "Acme funds health." not in md
        assert "A ·" not in md and "Not recorded." in md

    def test_goals_as_a_list_and_empty(self):
        assert "## What it set out to find" in brief.entity_markdown(row(goals=["x"]))
        assert "## What it set out to find" not in brief.entity_markdown(row(goals="[]"))

    def test_prior_brief_facts_are_kept(self):
        first = brief.entity_markdown(row(findings=[ev(concept="contact", name="Kept Person", role="CEO")]))
        again = brief.entity_markdown(row(findings=[]), prior=first)
        assert "Kept Person" in again


class TestStorage:
    async def test_build_and_publish(self, monkeypatch):
        prior = brief.entity_markdown(row(findings=[ev(concept="contact", name="Kept", role="CEO")])).encode()
        uploads = []

        async def read(bucket, key):
            assert key == storage.brief_key("acme")
            return prior

        async def upload(bucket, key, data, kind, replace):
            uploads.append((key, data.decode(), kind, replace))
            return key
        monkeypatch.setattr(storage, "read", read)
        monkeypatch.setattr(storage, "upload", upload)
        key = await brief.publish(row(findings=[ev(concept="contact", name="New", role="CFO")]))
        assert key == storage.brief_key("acme")
        assert "Kept" in uploads[0][1] and "New" in uploads[0][1] and uploads[0][2:] == ("text/markdown", True)

    async def test_promotable_merges_brief_facts_and_keeps_private(self, monkeypatch):
        held = brief.entity_markdown(row(findings=[ev(concept="contact", name="Kept", role="CEO")]),
                                     unplaced=[{"field": "f", "value": "v", "evidence": "e", "source_url": SRC}],
                                     states={json.dumps(["contact", "kept", "ceo"]): {"state": "written"}})

        async def read(bucket, key):
            return held.encode()
        monkeypatch.setattr(storage, "read", read)
        r = row(findings=[ev(concept="identity", name="Acme"), ev(concept="identity", name="P", source_url=PRIVATE)])
        out = await brief.promotable(r, [])
        names = sorted(f["name"] for f in out["findings"])
        assert names == ["Acme", "Kept", "P"]
        assert all(brief.STATE not in f for f in out["findings"]) and out["unplaced"][0]["field"] == "f"

    async def test_promotable_without_a_brief(self, monkeypatch):
        async def read(bucket, key):
            return None
        monkeypatch.setattr(storage, "read", read)
        out = await brief.promotable(row(findings=[{"label": "old", "value": 1}]), [])
        assert out["findings"] == [] and out["unplaced"] == []

    async def test_rows_for(self):
        class Conn:
            async def execute(self, sql, params):
                assert params == ("acme",)

                class C:
                    async def fetchall(self):
                        return [{"slug": "acme"}]
                return C()
        assert await brief.rows_for(Conn(), "acme") == [{"slug": "acme"}]
