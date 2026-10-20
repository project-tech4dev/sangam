"""promote() for an NGO: tier-ranked writes, fill-only partner lines, aliases another org already holds."""

from __future__ import annotations

import pytest

from app.ingest.promote import org_match, promote
from app.ingest.writer import Gate
from tests.test_cov_promote import finding, funder, money, no_storage, one, org, research, rows, states, tag

pytestmark = pytest.mark.integration
__all__ = ["no_storage"]

DOC = {"source_type": "org_document", "evidence_tier": "evidenced"}
REG = {"source_type": "registry", "evidence_tier": "evidenced"}
AGG = {"source_type": "aggregator", "evidence_tier": "claimed"}


def org_findings(name: str, site: str, gives: str) -> list[dict]:
    report = f"{site}/annual-report.pdf"
    return [
        finding("org_identity", f"{site}/about", name=name, org_kind="cso", legal_form="Trust", website=site,
                description="Works with tribal girls in Assam.", aliases=[f"{name} Trust"], staff_count=40,
                themes=["skilling"], **DOC),
        finding("org_identifier", report, id_type="pan", id_value=f"AAATZ{tag()[:4].upper()}A", status="registered",
                **DOC),
        finding("org_identifier", report, id_type="80g", status="applied", application_ref="ACK123", **DOC),
        finding("org_financials", report, fiscal_year="FY2023-24", total_income=money(1.5), is_audited=True,
                **DOC),
        finding("org_location", report, state="Assam", district="Barpeta", role="registered", **DOC),
        finding("org_location", report, state="Assam", role="operates", **DOC),
        finding("program", f"{site}/work", name="Girls Learn", kind="programme", **DOC),
        finding("program", f"{site}/work", name="Untiered Programme", kind="programme"),
        finding("metric", report, name="Girls enrolled", value=500, program_name="Girls Learn", **DOC),
        finding("metric", report, name="Untiered metric", value=1),
        finding("contact", f"{site}/contact", name="Office", kind="other", email="info@example.org",
                is_role_mailbox=True, **DOC),
        finding("partner", report, fiscal_year="FY2023-24", funder_name=gives, partner_name=name,
                amount=money(0.2), project_name="Library", **DOC),
        finding("partner", report, fiscal_year="FY2023-24", funder_name="Qqxyzzy Unheard Of Fund",
                partner_name=name, **DOC),
        finding("partner", report, fiscal_year="FY2022-23", partner_name=name, **DOC),
    ]


async def test_a_new_ngo_is_written_with_its_registrations_money_places_and_funders(db):
    t = tag()
    name, site = f"Zz Cov Sanstha {t}", f"https://zz-sanstha-{t}.example.org"
    gives = f"Zz Giving Ltd {t}"
    fid = await funder(db, gives)
    # A funder line written before Sangam held this NGO, by an alias it will carry.
    early = await one(db, "INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name) "
                          "VALUES (%s, 'partner', 'FY2021-22', %s) RETURNING id", fid, f"{name} Trust")
    report = await promote(db, await research(db, name, org_findings(name, site, gives), kind="org"))

    assert report["entity"]["kind"] == "org" and report["entity"]["status"] == "added"
    oid = report["entity"]["id"]
    stored = await one(db, "SELECT * FROM orgs WHERE id = %s", oid)
    assert stored["source_type"] == "org_document" and stored["evidence"] == "evidenced"
    assert stored["registered_location_id"] is not None and stored["staff_count"] == 40
    assert all(stored[c] for c in ("source_url", "source_name", "fetched_at", "content_hash", "extractor_version"))
    assert (await one(db, "SELECT partner_org_id FROM funder_activity WHERE id = %s", early["id"]))[
        "partner_org_id"] == oid
    assert report["written"]["funder_activity (partner link)"]["updated"] == 1

    ids = {r["id_type"]: r for r in await rows(db, "SELECT * FROM org_identifiers WHERE org_id = %s", oid)}
    assert ids["pan"]["status"] == "registered" and ids["80g"]["application_ref"] == "ACK123"
    fin = await one(db, "SELECT * FROM org_financials WHERE org_id = %s", oid)
    assert float(fin["total_income"]) == 1.5e7 and fin["is_audited"]
    assert (await one(db, "SELECT count(*) AS n FROM org_locations WHERE org_id = %s", oid))["n"] == 2
    assert await one(db, "SELECT 1 FROM programs WHERE org_id = %s AND name = 'Girls Learn'", oid)
    assert not await one(db, "SELECT 1 FROM programs WHERE org_id = %s AND name = 'Untiered Programme'", oid)
    assert await one(db, "SELECT 1 FROM metrics WHERE org_id = %s AND name = 'Girls enrolled'", oid)
    assert await one(db, "SELECT 1 FROM contacts WHERE org_id = %s", oid)

    line = await one(db, "SELECT * FROM funder_activity WHERE funder_id = %s AND fiscal_year = 'FY2023-24'", fid)
    assert line["partner_org_id"] == oid and line["partner_name"] == name and float(line["amount"]) == 2e6
    held = " ".join(report["held"])
    assert "needs source_type and evidence_tier" in held
    assert "Qqxyzzy Unheard Of Fund" in held and "needs funder_name" in held
    assert "written" in states(report) and "held" in states(report)


async def test_an_ngo_funder_line_fills_the_funders_own_line_and_reports_a_differing_title(db):
    t = tag()
    name = f"Zz Line Samiti {t}"
    gives = f"Zz Line Giver Ltd {t}"
    fid = await funder(db, gives)
    oid = await org(db, name)
    await db.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
                     "project_name) VALUES (%s, 'partner', 'FY2023-24', %s, %s, 'Clinic')", (fid, name, oid))
    url = "https://zz-line.example.org/report"
    report = await promote(db, await research(db, name, [
        finding("org_identity", url, name=name, **DOC),
        finding("partner", url, fiscal_year="FY2023-24", funder_name=gives, partner_name=f"{name} Society",
                project_name="Mobile health", amount=money(0.1), **DOC),
    ], kind="org"))
    assert report["entity"]["id"] == oid
    assert any("project_name" in c and "Clinic" in c for c in report["conflicts"])
    lines = await rows(db, "SELECT * FROM funder_activity WHERE funder_id = %s", fid)
    assert len(lines) == 1 and lines[0]["project_name"] == "Clinic"


async def test_two_funder_lines_for_one_ngo_and_year_are_held_for_a_person(db):
    t = tag()
    name = f"Zz Twice Samiti {t}"
    gives = f"Zz Twice Giver Ltd {t}"
    fid = await funder(db, gives)
    oid = await org(db, name)
    for project in ("A", "B"):
        await db.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
                         "project_name) VALUES (%s, 'partner', 'FY2023-24', %s, %s, %s)", (fid, name, oid, project))
    url = "https://zz-twice.example.org/report"
    report = await promote(db, await research(db, name, [
        finding("org_identity", url, name=name, **DOC),
        finding("partner", url, fiscal_year="FY2023-24", funder_name=gives, partner_name=name, **DOC),
    ], kind="org"))
    assert any("already has 2 lines" in h for h in report["held"])


async def test_a_stronger_source_takes_the_row_and_a_weaker_one_is_a_conflict(db):
    t = tag()
    name = f"Zz Ranked Sanstha {t}"
    oid = await org(db, name, legal_form="Society", source_type="aggregator", evidence="claimed",
                    source_url="https://aggregator.example.org")
    url = "https://zz-ranked.example.org/deed"
    taken = await promote(db, await research(db, name, [
        finding("org_identity", url, name=name, legal_form="Trust", **DOC)], kind="org"))
    assert taken["entity"]["status"] == "updated"
    stored = await one(db, "SELECT legal_form, source_type, source_url FROM orgs WHERE id = %s", oid)
    assert stored == {"legal_form": "Trust", "source_type": "org_document", "source_url": url}

    weaker = await promote(db, await research(db, name, [
        finding("org_identity", "https://x.example.org", name=name, legal_form="Company",
                source_type="funder", evidence_tier="evidenced")], kind="org", slug=f"zz-weak-{t}"))
    assert any("legal_form" in c and "'Trust'" in c for c in weaker["conflicts"])
    assert (await one(db, "SELECT legal_form FROM orgs WHERE id = %s", oid))["legal_form"] == "Trust"


async def test_an_alias_another_ngo_answers_to_is_held_not_added(db):
    t = tag()
    other = await org(db, f"Zz Shared Name {t}")
    name = f"Zz Alias Owner {t}"
    report = await promote(db, await research(db, name, [
        finding("org_identity", "https://x.example.org", name=name, aliases=[f"Zz Shared Name {t}"], **DOC)],
        kind="org"))
    assert any(f"[org:{other}]" in h for h in report["held"])
    aliases = (await one(db, "SELECT aliases FROM orgs WHERE id = %s", report["entity"]["id"]))["aliases"]
    assert f"Zz Shared Name {t}" not in (aliases or [])


async def test_an_ngo_parent_is_linked_when_held_and_reported_when_not(db):
    t = tag()
    parent = await org(db, f"Zz Mother Network {t}")
    name = f"Zz Daughter Unit {tag()}"
    report = await promote(db, await research(db, name, [
        finding("org_identity", "https://x.example.org", name=name, parent_name=f"Zz Mother Network {t}", **DOC)],
        kind="org"))
    assert (await one(db, "SELECT parent_id FROM orgs WHERE id = %s", report["entity"]["id"]))["parent_id"] == parent

    lone = f"Zz Lone Unit {tag()}"
    report = await promote(db, await research(db, lone, [
        finding("org_identity", "https://x.example.org", name=lone, parent_name="Qqxyzzy Nobody Network", **DOC)],
        kind="org"))
    assert any("not an organisation Sangam holds" in h for h in report["held"])


async def test_an_ngo_with_no_tiered_identity_is_not_built(db):
    report = await promote(db, await research(db, "Zz Untiered", [
        finding("org_identity", "https://x.example.org", name="Zz Untiered")], kind="org"))
    assert report["entity"] is None and "no org_identity" in report["reasons"][0]


async def test_a_number_another_ngo_holds_is_held(db):
    t = tag()
    holder = await org(db, f"Zz Pan Holder {t}")
    pan = f"AAAPZ{t[:4].upper()}Q"
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) VALUES (%s, 'pan', %s, "
                     "'registered')", (holder, pan))
    name = f"Zz Pan Claimant {tag()}"
    report = await promote(db, await research(db, name, [
        finding("org_identity", "https://x.example.org", name=name, **DOC),
        finding("org_identifier", "https://x.example.org/r", id_type="pan", id_value=pan, status="expired", **DOC),
    ], kind="org"))
    assert report["entity"]["id"] != holder
    assert any("org_id" in c and f"[org:{holder}]" in c for c in report["conflicts"])


async def test_identifier_statuses_against_a_stored_registration(db):
    t = tag()
    name = f"Zz Status Sanstha {t}"
    oid = await org(db, name)
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, source_type, evidence) "
                     "VALUES (%s, '12a', %s, 'registered', 'registry', 'evidenced')", (oid, f"12A-{t}"))
    url = "https://x.example.org/r"
    report = await promote(db, await research(db, name, [
        finding("org_identity", url, name=name, **DOC),
        finding("org_identifier", url, id_type="12a", status="applied", application_ref="ACK-9", **DOC),
        finding("org_identifier", url, id_type="12a", status="check_blocked", **DOC),
    ], kind="org"))
    row = await one(db, "SELECT application_ref, status FROM org_identifiers WHERE org_id = %s AND id_type = '12a'",
                    oid)
    assert row == {"application_ref": "ACK-9", "status": "registered"}
    assert any("applied" in c for c in report["conflicts"])


async def test_org_match_follows_an_earlier_save_and_a_gate_answer(db):
    t = tag()
    name = f"Zz Matched Sanstha {t}"
    oid = await org(db, name)
    row = await research(db, name, [finding("org_identity", "https://x.example.org", name=name, **DOC)], kind="org")
    assert (await org_match(db, row)).entity_id == oid

    await org(db, f"Zqvortex Harmony Sanstha {t}")
    near = f"Zqvortex Harmonia Sanstha {t}"
    waiting = await promote(db, await research(db, near, [
        finding("org_identity", "https://x.example.org", name=near, **DOC)], kind="org"), gate=Gate())
    assert waiting["entity"] is None and waiting["questions"]
    assert any("waiting for a person" in h for h in waiting["held"])
