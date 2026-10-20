"""The Import writers on real tables: the gate's five cases, CHECK refusals asked first, tier-ranked org rows."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.ingest import writer
from app.ingest.matcher import Match
from app.ingest.promote import promote
from app.ingest.records import FunderRecord, OrgIdentifierRecord
from app.ingest.writer import GATE, Gate, Owner
from tests.test_cov_promote import finding, funder, money, no_storage, one, org, research, rows, tag

pytestmark = pytest.mark.integration
__all__ = ["no_storage"]

NOW = datetime(2026, 1, 1, tzinfo=UTC)
DOC = {"source_type": "org_document", "evidence_tier": "evidenced"}


def rec(**fields) -> SimpleNamespace:
    base = {"source_url": "https://w.example.org/r", "source_name": "report", "fetched_at": NOW, "as_of": None,
            "content_hash": "h", "extractor_version": "test", "notes": None}
    return SimpleNamespace(**(base | fields))


class gated:
    """Sets the import gate for a direct writer call, as promote() does."""

    def __init__(self, gate: Gate | None) -> None:
        self.gate = gate

    def __enter__(self) -> Gate | None:
        self.token = GATE.set(self.gate)
        return self.gate

    def __exit__(self, *exc) -> None:
        GATE.reset(self.token)


# --- the gate through promote -------------------------------------------------------------------


async def test_a_programme_spelled_close_to_a_stored_one_is_asked_and_renamed_on_update(db):
    t = tag()
    name = f"Zz Gate Ltd {t}"
    fid = await funder(db, name)
    pid = (await one(db, "INSERT INTO programs (funder_id, name) VALUES (%s, 'Rural Livelihoods Mission') "
                         "RETURNING id", fid))["id"]
    findings = [finding("identity", "https://x.example.org", name=name),
                finding("program", "https://x.example.org/p", name="Rural Livelihood Mission")]
    asked = await promote(db, await research(db, name, findings), gate=Gate())
    question = next(q for q in asked["questions"] if q["table"] == "programs")
    assert question["case"] == 4 and question["row"] == f"[programs:{pid}]"

    skipped = await promote(db, await research(db, name, findings, slug=f"zz-skip-{t}"),
                            gate=Gate({question["id"]: "skip"}))
    assert any(i["outcome"] == "skipped" for i in skipped["plan"]["items"])
    assert (await one(db, "SELECT name FROM programs WHERE id = %s", pid))["name"] == "Rural Livelihoods Mission"

    await promote(db, await research(db, name, findings, slug=f"zz-upd-{t}"), gate=Gate({question["id"]: "update"}))
    assert (await one(db, "SELECT name FROM programs WHERE id = %s", pid))["name"] == "Rural Livelihood Mission"
    assert (await one(db, "SELECT count(*) AS n FROM programs WHERE funder_id = %s", fid))["n"] == 1


async def test_a_newer_csr_year_updates_under_the_gate_and_reports_the_change(db):
    t = tag()
    name = f"Zz Year Ltd {t}"
    fid = await funder(db, name)
    await db.execute("INSERT INTO funder_csr_years (funder_id, fiscal_year, total_spent, as_of) "
                     "VALUES (%s, 'FY2023-24', 1000, 'FY2022-23')", (fid,))
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name),
        finding("csr_year", "https://x.example.org/r", fiscal_year="FY2023-24", total_spent=money(2)),
    ]), gate=Gate())
    assert report["csr_years"] == [{"fiscal_year": "FY2023-24", "status": "updated"}]
    assert any(c["table"] == "funder_csr_years" and c["case"] == 2 for c in report["changes"])
    year = await one(db, "SELECT total_spent FROM funder_csr_years WHERE funder_id = %s", fid)
    assert float(year["total_spent"]) == 2e7


async def test_a_plan_over_a_stored_funder_changes_nothing(db):
    t = tag()
    name = f"Zz Plan Stored Ltd {t}"
    fid = await funder(db, name, legal_form="Trust")
    await db.execute("INSERT INTO programs (funder_id, name) VALUES (%s, 'Water')", (fid,))
    await db.execute("INSERT INTO funder_csr_years (funder_id, fiscal_year, total_spent) "
                     "VALUES (%s, 'FY2023-24', 1000)", (fid,))
    url = "https://x.example.org/r"
    report = await promote(db, await research(db, name, [
        finding("identity", url, name=name, legal_form="Company", themes=["skilling"]),
        finding("csr_year", url, fiscal_year="FY2023-24", total_spent=money(2)),
        finding("program", url, name="Water", description="Clean water for villages"),
        finding("program", url, name="Water Phase Two", kind="phase", parent_name="Water"),
        finding("csr_spend", url, fiscal_year="FY2023-24", amount=money(1), project_name="Wells",
                sector="Rural development", domain="health", classified_by="filed_sector", program_name="Water"),
        finding("stated_geography", url, state="Assam", role="registered"),
        finding("rfp", url, title="Call for wells", sector="Rural development"),
        finding("eligibility_guideline", url, title="Partner selection", own_bar="Audited accounts."),
        finding("document", url, title="Annual report", doc_type="annual_report"),
    ]), gate=Gate(plan=True))
    assert report["entity"]["id"] == fid
    assert (await one(db, "SELECT legal_form, registered_location_id FROM funders WHERE id = %s", fid)) == {
        "legal_form": "Trust", "registered_location_id": None}
    assert float((await one(db, "SELECT total_spent FROM funder_csr_years WHERE funder_id = %s", fid))[
        "total_spent"]) == 1000
    assert (await one(db, "SELECT count(*) AS n FROM programs WHERE funder_id = %s", fid))["n"] == 1
    assert not await one(db, "SELECT 1 FROM funder_activity WHERE funder_id = %s", fid)
    assert not await one(db, "SELECT 1 FROM rfps WHERE funder_id = %s", fid)
    assert not await one(db, "SELECT 1 FROM documents WHERE funder_id = %s", fid)
    assert {i["outcome"] for i in report["plan"]["items"]} <= {"planned", "asked", "held"}


async def test_re_promoting_under_the_gate_counts_rows_that_did_not_change(db):
    t = tag()
    name = f"Zz Same Ltd {t}"
    url = "https://x.example.org/r"
    findings = [finding("identity", url, name=name),
                finding("csr_year", url, fiscal_year="FY2023-24", total_spent=money(2)),
                finding("metric", url, name="Wells dug", value=4, period="FY2023-24")]
    first = await promote(db, await research(db, name, findings))
    again = await promote(db, await research(db, name, findings, slug=f"zz-same-{t}"), gate=Gate())
    assert again["entity"]["id"] == first["entity"]["id"] and again["plan"]["same"] >= 2
    assert again["csr_years"][0]["status"] == "matched"


# --- writers called directly -------------------------------------------------------------------


async def test_ensure_document_types_and_fills_a_row_first_seen_as_a_url(db):
    url = f"https://zz-doc-{tag()}.example.org/report.pdf"
    fid = await funder(db, f"Zz Doc Ltd {tag()}")
    owner = Owner.funder(fid)
    first, status = await writer.ensure_document(db, rec(source_url=url, title=None), owner=owner, doc_type="other")
    assert status == "added"
    again, status = await writer.ensure_document(db, rec(source_url=url, title="Annual report"), owner=owner,
                                                 doc_type="annual_report", storage_path="b/k.pdf",
                                                 content_hash="abc")
    assert (again, status) == (first, "updated")
    row = await one(db, "SELECT doc_type, title, storage_path, content_hash FROM documents WHERE id = %s", first)
    assert row == {"doc_type": "annual_report", "title": "Annual report", "storage_path": "b/k.pdf",
                   "content_hash": "abc"}
    assert (await writer.ensure_document(db, rec(source_url=url), owner=owner, doc_type="annual_report"))[1] == \
        "matched"


async def test_activity_lines_the_tables_checks_would_refuse_are_held_first(db):
    fid = await funder(db, f"Zz Check Ltd {tag()}")
    spend = rec(activity_kind="spend", fiscal_year="FY2023-24", designation=None, project_name="P",
                partner_name=None, classified_by=None, classification_note=None, implementation_mode=None,
                partner_csr1=None, outlay=None, amount=None, project_count=None, is_ongoing=None)
    status, why = await writer.write_csr_spend(db, spend, fid, program_id=None, state_id=None, district_id=None,
                                               csr_sector_id=None, domain_id=None, theme_id=None, document_id=None)
    assert (status, why) == ("held", {"reason": "a spend line needs an amount"})

    domain = (await one(db, "SELECT id FROM tags WHERE kind = 'domain' LIMIT 1"))["id"]
    spend.amount = 10.0
    status, why = await writer.write_csr_spend(db, spend, fid, program_id=None, state_id=None, district_id=None,
                                               csr_sector_id=None, domain_id=domain, theme_id=None, document_id=None)
    assert why["reason"].startswith("a domain needs classified_by")

    foot = rec(activity_kind="footprint", fiscal_year="FY2023-24", name_as_printed=None)
    status, why = await writer.write_footprint(db, foot, fid, program_id=None, state_id=None, district_id=None,
                                               document_id=None)
    assert why == {"reason": "a footprint line needs a place"}

    prog = rec(activity_kind="programme", fiscal_year="FY2023-24", classified_by="report",
               classification_note=None, amount=None)
    status, why = await writer.write_programme_spend(db, prog, fid, program_id=None, domain_id=None, theme_id=None,
                                                     document_id=None)
    assert why["reason"].startswith("a programme line needs")
    assert not await one(db, "SELECT 1 FROM funder_activity WHERE funder_id = %s", fid)


async def test_a_confirmed_classification_is_never_re_inferred(db):
    fid = await funder(db, f"Zz Confirmed Ltd {tag()}")
    tags = await rows(db, "SELECT id FROM tags WHERE kind = 'domain' ORDER BY id LIMIT 2")
    await db.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, project_name, amount, "
                     "domain_tag_id, classified_by, classification_confirmed) "
                     "VALUES (%s, 'spend', 'FY2023-24', 'Wells', 5, %s, 'report', true)", (fid, tags[0]["id"]))
    spend = rec(activity_kind="spend", fiscal_year="FY2023-24", designation=None, project_name="Wells",
                partner_name=None, classified_by="filed_sector", classification_note=None, implementation_mode=None,
                partner_csr1=None, outlay=None, amount=7.0, project_count=None, is_ongoing=None)
    status, _ = await writer.write_csr_spend(db, spend, fid, program_id=None, state_id=None, district_id=None,
                                             csr_sector_id=None, domain_id=tags[1]["id"], theme_id=None,
                                             document_id=None)
    line = await one(db, "SELECT amount, domain_tag_id, classified_by FROM funder_activity WHERE funder_id = %s", fid)
    assert status == "updated" and float(line["amount"]) == 7
    assert (line["domain_tag_id"], line["classified_by"]) == (tags[0]["id"], "report")


async def test_an_ngo_partner_line_never_overwrites_the_funders_amount(db):
    fid = await funder(db, f"Zz Guard Ltd {tag()}")
    await db.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, amount, notes, "
                     "source_url, source_type, evidence) VALUES (%s, 'partner', 'FY2023-24', 'Zz NGO', 100, "
                     "'first line', 'https://funder.example.org', 'funder', 'evidenced')", (fid,))
    line = rec(activity_kind="partner", fiscal_year="FY2023-24", project_name=None, partner_name="Zz NGO",
               partner_canonical=None, partner_kind=None, partner_csr1=None, outlay=None, amount=200.0,
               start_date=None, end_date=None, relationship_status="active", notes="first line\nsecond line",
               source_type="aggregator", evidence_tier="claimed")
    found: list = []
    status, _ = await writer.write_partner(db, line, fid, program_id=None, document_id=None, fill_only=True,
                                           conflicts=found)
    stored = await one(db, "SELECT amount, notes, relationship_status, source_type FROM funder_activity "
                           "WHERE funder_id = %s", fid)
    assert status == "updated" and float(stored["amount"]) == 100
    assert stored["notes"] == "first line\nsecond line" and stored["relationship_status"] == "active"
    assert stored["source_type"] == "funder"
    assert sorted(c.column for c in found) == ["amount", "source_url"]


async def test_tags_skip_an_invented_code_and_add_a_real_one_once(db):
    fid = await funder(db, f"Zz Tags Ltd {tag()}")
    tagged = SimpleNamespace(themes=["skilling", "not-a-code"], populations=[], lenses=[], tag_note="n")
    added, reasons = await writer.write_tags(db, "funder_id", fid, tagged)
    assert added == 1 and reasons == ["theme 'not-a-code' is not a taxonomy code; dropped"]
    assert (await writer.write_tags(db, "funder_id", fid, tagged))[0] == 0
    with gated(Gate(plan=True)):
        assert await writer.write_tags(db, "funder_id", fid, tagged) == (0, [])


async def test_an_eligibility_document_follows_the_newest_text(db):
    fid = await funder(db, f"Zz Elig Ltd {tag()}")
    url = f"https://zz-elig-{tag()}.example.org/policy"
    base = {"source_url": url, "title": "Partner selection", "statutory_restatement": None,
            "disqualifiers": None, "not_stated": False, "as_of": None, "doc_type": "funder_eligibility"}
    first = rec(**base, own_bar="Audited accounts.")
    first.content_md = lambda: "## Its own bar\n\nAudited accounts."
    doc, status = await writer.write_eligibility_document(db, first, fid)
    assert status == "added"
    assert (await writer.write_eligibility_document(db, first, fid))[1] == "matched"
    second = rec(**base, own_bar="Three years.")
    second.content_md = lambda: "## Its own bar\n\nThree years."
    assert await writer.write_eligibility_document(db, second, fid) == (doc, "updated")
    with gated(Gate(plan=True)):
        assert await writer.write_eligibility_document(db, second, fid) == (0, "planned")


async def test_set_registered_location_fills_only_a_blank(db):
    oid = await org(db, f"Zz Reg Org {tag()}")
    states = await rows(db, "SELECT id FROM locations WHERE kind = 'state' ORDER BY id LIMIT 2")
    assert await writer.set_registered_location(db, Owner.org(oid), states[0]["id"])
    assert not await writer.set_registered_location(db, Owner.org(oid), states[1]["id"])
    with gated(Gate(plan=True)):
        assert not await writer.set_registered_location(db, Owner.org(oid), states[1]["id"])
    assert (await one(db, "SELECT registered_location_id FROM orgs WHERE id = %s", oid))[
        "registered_location_id"] == states[0]["id"]


async def test_write_funder_appends_aliases_and_a_plan_returns_unwritten(db):
    name = f"Zz Alias Ltd {tag()}"
    fid = await funder(db, name, aliases=["Old Spelling"])
    record = FunderRecord(name=name, aliases=["old spelling", "New Spelling"], source_url="https://x.example.org",
                          source_name="r", fetched_at=NOW, content_hash="h", extractor_version="v")
    status, _, changes = await writer.write_funder(db, record, Match("exact", fid))
    assert status == "updated" and changes["aliases"]["new"] == ["Old Spelling", "New Spelling"]
    with gated(Gate(plan=True)) as gate:
        status, new_id, _ = await writer.write_funder(db, record.model_copy(update={"name": f"Zz Brand New {tag()}"}),
                                                      Match("none"))
    assert (status, new_id) == ("added", writer.UNWRITTEN) and gate.items[0]["case"] == 5


# --- org identifiers ----------------------------------------------------------------------------


def ident(**fields) -> OrgIdentifierRecord:
    base = {"entity_name": "Zz Org", "id_type": "fcra", "status": "registered", "source_url": "https://x.example.org",
            "source_name": "r", "fetched_at": NOW, "source_type": "org_document", "evidence_tier": "evidenced"}
    return OrgIdentifierRecord(**(base | fields))


async def test_a_number_from_a_weaker_source_than_the_open_row_is_its_own_row(db):
    oid = await org(db, f"Zz Fcra Org {tag()}")
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, status, source_type, evidence) "
                     "VALUES (%s, 'fcra', 'not_found', 'registry', 'evidenced')", (oid,))
    status, _, found = await writer.write_org_identifier(db, ident(id_value=f"FCRA{tag()}"), oid, None)
    assert status == "added" and [c.column for c in found] == ["status"]
    assert (await one(db, "SELECT count(*) AS n FROM org_identifiers WHERE org_id = %s", oid))["n"] == 2


async def test_a_blocked_check_confirms_nothing_and_any_finding_replaces_it(db):
    oid = await org(db, f"Zz Blocked Org {tag()}")
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, status, source_type, evidence) "
                     "VALUES (%s, 'fcra', 'check_blocked', 'registry', 'evidenced')", (oid,))
    status, _, found = await writer.write_org_identifier(db, ident(status="check_blocked", id_value=None), oid, None)
    assert (status, found) == ("matched", [])
    number = f"FCRA{tag()}"
    status, _changes, _ = await writer.write_org_identifier(
        db, ident(id_value=number, source_type="aggregator", evidence_tier="claimed"), oid, None)
    row = await one(db, "SELECT id_value, status, source_type FROM org_identifiers WHERE org_id = %s", oid)
    assert status == "updated" and row == {"id_value": number, "status": "registered", "source_type": "aggregator"}


async def test_a_status_with_no_number_updates_the_one_current_registration(db):
    oid = await org(db, f"Zz Expired Org {tag()}")
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, source_type, evidence) "
                     "VALUES (%s, 'fcra', %s, 'registered', 'aggregator', 'claimed')", (oid, f"FC{tag()}"))
    status, _, _ = await writer.write_org_identifier(
        db, ident(status="not_available", id_value=None, source_type="registry"), oid, None)
    row = await one(db, "SELECT count(*) AS n, min(status) AS status FROM org_identifiers WHERE org_id = %s", oid)
    assert status == "updated" and row == {"n": 1, "status": "not_available"}


async def test_an_application_with_no_stronger_registration_fills_the_open_row(db):
    oid = await org(db, f"Zz Applied Org {tag()}")
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, status, source_type, evidence) "
                     "VALUES (%s, '80g', 'not_found', 'aggregator', 'claimed')", (oid,))
    status, _, _found = await writer.write_org_identifier(
        db, ident(id_type="80g", status="applied", id_value=None, application_ref="ACK-1"), oid, None)
    row = await one(db, "SELECT status, application_ref, source_type FROM org_identifiers WHERE org_id = %s", oid)
    assert status == "updated" and row == {"status": "applied", "application_ref": "ACK-1",
                                           "source_type": "org_document"}
