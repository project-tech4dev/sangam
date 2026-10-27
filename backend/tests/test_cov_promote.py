"""promote() end to end against real Postgres: findings in, catalog rows out, every hold and merge reported."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.ingest import promote as promote_mod
from app.ingest.promote import EXTRACTOR_VERSION, promote
from app.ingest.writer import Gate

pytestmark = pytest.mark.integration

PROV = ("source_url", "source_name", "fetched_at", "content_hash", "extractor_version")
EVIDENCE = "The annual report states this plainly on the page cited here."


def tag() -> str:
    return uuid.uuid4().hex[:8]


def money(crore: float) -> dict[str, Any]:
    return {"value": crore, "unit": "crore", "text": f"Rs {crore} crore"}


def finding(concept: str, source: str, /, **fields: Any) -> dict[str, Any]:
    return {"concept": concept, "evidence": EVIDENCE, "source_url": source, "source_name": "Annual report",
            "confidence": "high", **fields}


@pytest.fixture(autouse=True)
def no_storage(monkeypatch):
    """No archive: CI has no Supabase, and a real move could not be rolled back."""
    async def none(bucket, url):
        return None
    monkeypatch.setattr(promote_mod.storage, "archived_key", none)


async def research(db, name: str, findings: list[dict], *, kind: str = "funder", version: int = 2,
                   slug: str | None = None, website: str | None = None) -> dict[str, Any]:
    slug = slug or f"zz-cov-{tag()}"
    row = await (await db.execute(
        "INSERT INTO entity_research (entity_name, canonical_name, entity_kind, slug, status, summary, findings, "
        "fact_count, schema_version, website) VALUES (%s, %s, %s, %s, 'complete', 'a summary', %s::jsonb, %s, %s, %s) "
        "RETURNING *",
        (name, name, kind, slug, json.dumps(findings, default=str), len(findings), version, website),
    )).fetchone()
    return dict(row)


async def one(db, sql: str, *params) -> dict[str, Any] | None:
    return await (await db.execute(sql, params)).fetchone()


async def rows(db, sql: str, *params) -> list[dict[str, Any]]:
    return await (await db.execute(sql, params)).fetchall()


async def funder(db, name: str, **cols: Any) -> int:
    cols = {"slug": f"zz-f-{tag()}", "name": name, **cols}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return (await one(db, f"INSERT INTO funders ({names}) VALUES ({marks}) RETURNING id", *cols.values()))["id"]


async def org(db, name: str, **cols: Any) -> int:
    cols = {"slug": f"zz-o-{tag()}", "name": name, **cols}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return (await one(db, f"INSERT INTO orgs ({names}) VALUES ({marks}) RETURNING id", *cols.values()))["id"]


def written(report: dict, table: str, status: str = "added") -> int:
    return report["written"].get(table, {}).get(status, 0)


def states(report: dict) -> list[str]:
    return [v["state"] for v in report["facts"].values()]


# --- funder: a full first save ------------------------------------------------------------------


def funder_findings(name: str, site: str) -> list[dict]:
    report = f"{site}/annual-report-2024.pdf"
    page = f"{site}/csr"
    return [
        finding("identity", page, name=name, funder_type="csr_foundation", website=site,
                grant_size_min=money(0.1), grant_size_max=money(1), legal_form="Section 8 Company",
                founded_year=2001, themes=["skilling"], populations=["women"], aliases=[f"{name} CSR"]),
        finding("document", report, title="Annual Report 2023-24", doc_type="annual_report",
                as_of="FY2023-24"),
        finding("csr_year", report, fiscal_year="FY2023-24", prescribed_csr=money(12.5), total_spent=money(13),
                impact_assessment_done=True, page="88"),
        finding("program", page, name="Sustainable Livelihood Programme", kind="programme"),
        finding("program", page, name="Skills for Youth", kind="component",
                parent_name="Sustainable Livelihood Programme"),
        finding("program", page, name="Orphan Child", kind="component", parent_name="Nowhere Programme"),
        finding("csr_spend", report, fiscal_year="FY2023-24", amount=money(2), project_name="Clean water",
                sector="Healthcare and sanitation", domain="health", classified_by="filed_sector",
                state="Assam", program_name="Skills for Youth", page="90"),
        finding("csr_spend", report, fiscal_year="FY2023-24", amount=money(3), project_name="Clean water",
                sector="Healthcare and sanitation", domain="health", classified_by="filed_sector",
                state="Assam", program_name="Skills for Youth"),
        finding("csr_spend", report, fiscal_year="FY2023-24", amount=money(1), project_name="Bad domain",
                domain="nonsense", classified_by="filed_sector"),
        finding("csr_spend", report, fiscal_year="FY2023-24", amount=money(1), project_name="Ghost",
                domain="health", classified_by="filed_sector", program_name="Unknown Programme"),
        finding("footprint", report, fiscal_year="FY2023-24", state="Assam"),
        finding("footprint", report, fiscal_year="FY2023-24", state="Atlantis"),
        finding("stated_geography", page, state="Maharashtra", role="registered"),
        finding("partner", report, fiscal_year="FY2023-24", partner_name="Pratham Zz Partner", amount=money(0.5),
                project_name="Reading camps"),
        finding("programme_spend", report, fiscal_year="FY2023-24", program_name="Sustainable Livelihood Programme",
                amount=money(4), domain="livelihoods", classified_by="report"),
        finding("programme_spend", report, fiscal_year="FY2023-24", program_name="SLP - Ecosystem Action",
                amount=money(1), domain="livelihoods", classified_by="report"),
        finding("programme_spend", report, fiscal_year="FY2023-24", program_name="Not A Programme",
                amount=money(1), domain="livelihoods", classified_by="report"),
        finding("metric", report, name="Youth trained", value=1200, unit="people", period="FY2023-24"),
        finding("contact", page, name="Asha Rao", kind="grants", role="CSR Head", email="csr@example.org",
                is_role_mailbox=True),
        finding("rfp", page, title="Open call for water projects", status="open", url=f"{site}/apply",
                amount_max=money(0.5), sector="Healthcare", state="Assam"),
        finding("eligibility_guideline", f"{site}/policy", title="CSR Policy — partner selection",
                own_bar="Three years of audited accounts.", disqualifiers="Political bodies."),
        {"concept": "unknown_concept", "evidence": EVIDENCE, "source_url": page, "confidence": "low"},
        finding("csr_year", report, fiscal_year="2024"),  # not a fiscal year: refused by the model
    ]


async def test_a_new_funder_is_written_with_every_concept_and_its_provenance(db):
    t = tag()
    name, site = f"Zz Cov Foundation {t}", f"https://zz-cov-{t}.example.org"
    await org(db, "Pratham Zz Partner")
    row = await research(db, name, funder_findings(name, site))
    report = await promote(db, row)

    assert report["entity"]["kind"] == "funder" and report["entity"]["status"] == "added"
    fid = report["entity"]["id"]
    stored = await one(db, "SELECT * FROM funders WHERE id = %s", fid)
    assert stored["name"] == name and stored["website"] == site
    assert all(stored[c] for c in PROV) and stored["extractor_version"] == EXTRACTOR_VERSION
    assert float(stored["grant_size_max"]) == 1e7 and f"{name} CSR" in stored["aliases"]
    assert (await one(db, "SELECT resolved_funder_id FROM entity_research WHERE id = %s", row["id"]))[
        "resolved_funder_id"] == fid

    year = await one(db, "SELECT * FROM funder_csr_years WHERE funder_id = %s", fid)
    assert float(year["prescribed_csr"]) == 12.5e7 and year["document_id"] is not None
    assert report["csr_years"] == [{"fiscal_year": "FY2023-24", "status": "added"}]

    progs = {r["name"]: r for r in await rows(db, "SELECT * FROM programs WHERE funder_id = %s", fid)}
    assert progs["Skills for Youth"]["parent_id"] == progs["Sustainable Livelihood Programme"]["id"]
    assert progs["Ecosystem Action"]["parent_id"] == progs["Sustainable Livelihood Programme"]["id"]
    assert "Orphan Child" not in progs
    assert any("Orphan Child" in h and "Nowhere Programme" in h for h in report["held"])

    activity = await rows(db, "SELECT * FROM funder_activity WHERE funder_id = %s ORDER BY id", fid)
    kinds = sorted(a["kind"] for a in activity)
    assert kinds.count("spend") == 1 and "footprint" in kinds and "partner" in kinds
    spend = next(a for a in activity if a["kind"] == "spend")
    assert float(spend["amount"]) == 2e7 and spend["program_id"] == progs["Skills for Youth"]["id"]
    assert all(spend[c] for c in ("source_url", "source_name", "fetched_at"))
    partner = next(a for a in activity if a["kind"] == "partner")
    assert partner["partner_org_id"] is not None and partner["partner_name"] == "Pratham Zz Partner"
    assert sum(a["kind"] == "programme" for a in activity) == 2  # SLP and its new component

    assert any("two findings resolve to the same row" in h for h in report["held"])
    assert any("csr_spend finding refused (domain)" in h for h in report["held"])
    assert any("Unknown Programme" in h for h in report["held"])
    assert any("Atlantis" in h for h in report["held"])
    assert any("Not A Programme" in h for h in report["held"])
    assert report["skipped"] == {"unknown_concept": 1}

    registered = await one(db, "SELECT registered_location_id FROM funders WHERE id = %s", fid)
    assert registered["registered_location_id"] is not None
    assert await one(db, "SELECT 1 FROM funder_locations WHERE funder_id = %s", fid)
    assert await one(db, "SELECT 1 FROM metrics WHERE funder_id = %s AND name = 'Youth trained'", fid)
    assert await one(db, "SELECT 1 FROM contacts WHERE funder_id = %s AND email = 'csr@example.org'", fid)
    assert await one(db, "SELECT 1 FROM rfps WHERE funder_id = %s", fid)
    assert await one(db, "SELECT 1 FROM documents WHERE funder_id = %s AND doc_type = 'funder_eligibility'", fid)
    cited = await rows(db, "SELECT title FROM documents WHERE funder_id = %s AND doc_type = 'web_page'", fid)
    assert cited and all(r["title"] for r in cited) 
    assert await one(db, "SELECT 1 FROM funder_tags WHERE funder_id = %s", fid)
    links = await rows(db, "SELECT pages FROM document_links WHERE funder_id = %s", fid)
    assert any("88" in (r["pages"] or []) for r in links)
    assert "written" in states(report) and "no column" in states(report) and "held" in states(report)


async def test_promoting_the_same_research_again_matches_and_writes_no_twin(db):
    t = tag()
    name, site = f"Zz Again Foundation {t}", f"https://zz-again-{t}.example.org"
    findings = funder_findings(name, site)[:5]
    first = await promote(db, await research(db, name, findings, slug=f"zz-again-{t}"))
    # One research row per slug per day; yesterday's lets today's re-run find what it wrote.
    await db.execute("UPDATE entity_research SET researched_on = researched_on - 1 WHERE slug = %s", (f"zz-again-{t}",))
    again = await promote(db, await research(db, name, findings, slug=f"zz-again-{t}"))
    assert again["entity"]["id"] == first["entity"]["id"] and again["entity"]["status"] in ("matched", "updated")
    assert again["csr_years"][0]["status"] == "matched"
    assert (await one(db, "SELECT count(*) AS n FROM funders WHERE name = %s", name))["n"] == 1
    assert (await one(db, "SELECT count(*) AS n FROM programs WHERE funder_id = %s",
                      first["entity"]["id"]))["n"] == 2


async def test_research_matching_a_stored_funder_by_name_merges_into_it(db):
    t = tag()
    name = f"Zz Merge Industries {t}"
    fid = await funder(db, name, website="https://old.example.org")
    url = f"https://zz-merge-{t}.example.org/about"
    report = await promote(db, await research(db, name, [
        finding("identity", url, name=name, website=f"https://zz-merge-{t}.example.org", legal_form="Company")]))
    assert report["entity"] == {"kind": "funder", "status": "updated", "id": fid, "name": name}
    stored = await one(db, "SELECT * FROM funders WHERE id = %s", fid)
    assert stored["legal_form"] == "Company" and stored["source_url"] == url
    assert stored["content_hash"] and stored["extractor_version"] == EXTRACTOR_VERSION
    assert (await one(db, "SELECT count(*) AS n FROM funders WHERE lower(name) = lower(%s)", name))["n"] == 1


async def test_research_under_the_old_shape_is_not_promoted(db):
    report = await promote(db, await research(db, "Zz Old Shape", [
        finding("identity", "https://x.example.org", name="Zz Old Shape")], version=1))
    assert report["entity"] is None and "Re-run the research" in report["reasons"][0]


async def test_research_with_no_identity_builds_no_funder(db):
    report = await promote(db, await research(db, "Zz No Identity", [
        finding("metric", "https://x.example.org", name="Trees planted", value=10)]))
    assert report["entity"] is None
    assert report["reasons"] == ["no identity finding to build a funder from"]
    assert states(report) == ["held"]


# --- funder: constraints the stored row imposes -----------------------------------------------


CIN = "L12345MH2001PLC123456"


async def test_a_foundation_never_takes_a_cin(db):
    t = tag()
    name = f"Zz Cin Foundation {t}"
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name, cin=CIN)]))
    assert any("a CIN names a company" in h for h in report["held"])
    assert (await one(db, "SELECT cin FROM funders WHERE id = %s", report["entity"]["id"]))["cin"] is None


async def test_a_cin_another_funder_holds_is_not_written(db):
    t = tag()
    other = await funder(db, f"Aardvark Metals {t}", cin=CIN)
    name = f"Zz Claimant Pharma {tag()}"
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name, cin=CIN)]))
    assert any(f"[funder:{other}]" in h for h in report["held"])
    assert report["entity"]["id"] != other


async def test_a_differing_stored_cin_is_kept(db):
    t = tag()
    name = f"Zz Stored Cin Ltd {t}"
    fid = await funder(db, name, cin="U99999KA2010PTC000001")
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name, cin=CIN)]))
    assert any("differs from" in h for h in report["held"])
    assert (await one(db, "SELECT cin FROM funders WHERE id = %s", fid))["cin"] == "U99999KA2010PTC000001"


async def test_a_one_sided_band_that_inverts_the_stored_one_is_held(db):
    t = tag()
    name = f"Zz Band Ltd {t}"
    fid = await funder(db, name, grant_size_min=5e7, grant_size_max=1e8)
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name, grant_size_max=money(1))]))
    assert any("inverts the stored band" in h for h in report["held"])
    assert float((await one(db, "SELECT grant_size_max FROM funders WHERE id = %s", fid))["grant_size_max"]) == 1e8


async def test_a_parent_in_the_catalog_is_linked_and_one_outside_it_is_held(db):
    t = tag()
    parent = await funder(db, f"Zz Parent Bank {t}")
    child = f"Zz Kindred Foundation {tag()}"
    report = await promote(db, await research(db, child, [
        finding("identity", "https://x.example.org", name=child, parent_name=f"Zz Parent Bank {t}")]))
    assert (await one(db, "SELECT parent_id FROM funders WHERE id = %s", report["entity"]["id"]))[
        "parent_id"] == parent

    orphan = f"Zz Orphan Foundation {t}"
    report = await promote(db, await research(db, orphan, [
        finding("identity", "https://x.example.org", name=orphan, parent_name=f"Qqxyzzy Nonexistent {t}")]))
    assert any("is not in the catalog" in h for h in report["held"])


async def test_a_parent_that_only_resembles_a_funder_is_held(db):
    t = tag()
    await funder(db, f"Zqvortex Harmony Holdings {t}")
    child = f"Zz Resembles Foundation {t}"
    report = await promote(db, await research(db, child, [
        finding("identity", "https://x.example.org", name=child, parent_name=f"Zqvortex Harmonia Holdings {t}")]))
    assert any("resembles" in h and "Not linked" in h for h in report["held"])


# --- legacy shapes and guards ------------------------------------------------------------------


async def test_legacy_identifiers_and_grants_still_promote(db):
    t = tag()
    name = f"Zz Legacy Ltd {t}"
    url = "https://legacy.example.org/report"
    await org(db, f"Zz Legacy Grantee {t}")
    report = await promote(db, await research(db, name, [
        finding("identifier", url, id_type="cin", id_value="l12345mh2001plc654321"),
        finding("identifier", url, id_type="domain", id_value="legacy.example.org"),
        finding("identifier", url, id_type="name", id_value=f"Legacy Old Name {t}"),
        finding("grant", url, title="Library grant", recipient_name=f"Zz Legacy Grantee {t}",
                start_date="2023-06-01", amount=money(0.01), currency="INR"),
        finding("grant", url, title="Undated grant", recipient_name="Somebody"),
        finding("grant", url, title="Dollar grant", recipient_name="Somebody", end_date="2023-06-01",
                amount=money(0.01), currency="USD"),
    ]))
    fid = report["entity"]["id"]
    stored = await one(db, "SELECT * FROM funders WHERE id = %s", fid)
    assert stored["cin"] == "L12345MH2001PLC654321" and stored["website"] == "https://legacy.example.org"
    assert f"Legacy Old Name {t}" in stored["aliases"]
    line = await one(db, "SELECT * FROM funder_activity WHERE funder_id = %s AND kind = 'partner'", fid)
    assert line["fiscal_year"] == "FY2023-24" and line["partner_org_id"] is not None
    assert any("Undated grant" in h for h in report["held"]) and any("in USD" in h for h in report["held"])


async def test_an_aggregator_value_on_a_funder_is_held_by_the_source_guard(db):
    t = tag()
    name = f"Zz Guarded Ltd {t}"
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name),
        finding("metric", "https://www.guidestarindia.org/Summary.aspx?CCReg=1", name="Lives touched",
                value=5, source_type="aggregator", evidence_tier="claimed"),
    ]))
    assert any("stays research" in h for h in report["held"])
    assert not await one(db, "SELECT 1 FROM metrics WHERE funder_id = %s", report["entity"]["id"])


# --- the gate: plan, and changes asked about ---------------------------------------------------


async def test_a_plan_writes_nothing_and_lists_what_it_would_do(db):
    t = tag()
    name, site = f"Zz Plan Foundation {t}", f"https://zz-plan-{t}.example.org"
    report = await promote(db, await research(db, name, funder_findings(name, site)[:7]), gate=Gate(plan=True))
    assert report["entity"]["status"] == "added"
    assert not await one(db, "SELECT 1 FROM funders WHERE name = %s", name)
    assert report["plan"]["items"] and all(i["outcome"] in ("planned", "held") for i in report["plan"]["items"]
                                           if "outcome" in i)


async def test_an_older_source_changing_a_fact_is_asked_then_answered(db):
    t = tag()
    name = f"Zz Asked Ltd {t}"
    fid = await funder(db, name, legal_form="Trust", as_of="FY2024-25")
    findings = [finding("identity", "https://x.example.org", name=name, legal_form="Company", as_of="FY2021-22")]
    asked = await promote(db, await research(db, name, findings), gate=Gate())
    assert asked["questions"] and asked["questions"][0]["case"] == 3
    assert (await one(db, "SELECT legal_form FROM funders WHERE id = %s", fid))["legal_form"] == "Trust"

    item = asked["questions"][0]["id"]
    kept = await promote(db, await research(db, name, findings), gate=Gate({item: "keep"}))
    assert not kept["questions"]
    assert (await one(db, "SELECT legal_form FROM funders WHERE id = %s", fid))["legal_form"] == "Trust"
    await promote(db, await research(db, name, findings), gate=Gate({item: "update"}))
    assert (await one(db, "SELECT legal_form FROM funders WHERE id = %s", fid))["legal_form"] == "Company"


async def test_a_name_that_only_resembles_a_funder_waits_then_follows_the_answer(db):
    t = tag()
    stored = await funder(db, f"Zqvortex Harmony Holdings {t}")
    name = f"Zqvortex Harmonia Holdings {t}"
    waiting = await promote(db, await research(db, name, [finding("identity", "https://x.example.org", name=name)]),
                            gate=Gate())
    assert waiting["entity"] is None and waiting["questions"][0]["case"] == 4
    item = waiting["questions"][0]["id"]

    merged = await promote(db, await research(db, name, [finding("identity", "https://x.example.org", name=name)]),
                           gate=Gate({item: "update"}))
    assert merged["entity"]["id"] == stored
    assert name in (await one(db, "SELECT aliases FROM funders WHERE id = %s", stored))["aliases"]


async def test_a_resembling_name_answered_new_is_kept_apart(db):
    t = tag()
    stored = await funder(db, f"Zqvortex Harmony Holdings {t}")
    name = f"Zqvortex Harmonia Holdings {t}"
    findings = [finding("identity", "https://x.example.org", name=name)]
    item = (await promote(db, await research(db, name, findings), gate=Gate()))["questions"][0]["id"]
    apart = await promote(db, await research(db, name, findings, slug=f"zz-apart-{t}"), gate=Gate({item: "new"}))
    assert apart["entity"]["status"] == "added" and apart["entity"]["id"] != stored


async def test_without_a_gate_a_resembling_name_is_not_merged(db):
    t = tag()
    await funder(db, f"Zqvortex Harmony Holdings {t}")
    name = f"Zqvortex Harmonia Holdings {t}"
    report = await promote(db, await research(db, name, [finding("identity", "https://x.example.org", name=name)]))
    assert report["entity"] is None and any("a person decides" in r for r in report["reasons"])
