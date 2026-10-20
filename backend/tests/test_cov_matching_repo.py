"""The Funder Match reader on rows built here: what each side's profile carries, and who may save a run."""

from __future__ import annotations

import uuid

import pytest

from app.repositories import matching
from tests.test_cov_promote import funder, one, org, tag
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration
POLICY = ("## Statutory\n\nRegistered under 12A.\n\n## Its own bar\n\nThree years of accounts.\n\n"
          "Works in two states.\n\n## Disqualifiers\n\nPolitical bodies.")


async def _tag(db, slug: str) -> int:
    row = await one(db, "SELECT id FROM tags WHERE slug = %s", slug)
    if row is None:
        pytest.skip(f"taxonomy not seeded ({slug})")
    return row["id"]


async def _state(db, name: str) -> int:
    return (await one(db, "SELECT id FROM locations WHERE kind = 'state' AND name = %s", name))["id"]


async def _profiles(db):
    sub = await _tag(db, "sub_theme-vocational-foundational")
    women = await _tag(db, "population-women")
    domain = await _tag(db, "domain-health")
    assam, bihar = await _state(db, "Assam"), await _state(db, "Bihar")

    oid = await org(db, f"Zz Match Org {tag()}")
    await db.execute("INSERT INTO org_locations (org_id, location_id) VALUES (%s, %s)", (oid, assam))
    await db.execute("INSERT INTO org_tags (org_id, tag_id) VALUES (%s, %s)", (oid, women))
    pid = (await one(db, "INSERT INTO programs (org_id, name) VALUES (%s, 'Skills') RETURNING id", oid))["id"]
    await db.execute("INSERT INTO program_tags (program_id, tag_id) VALUES (%s, %s)", (pid, sub))
    await db.execute("INSERT INTO programs (org_id, name) VALUES (%s, 'Untagged')", (oid,))
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) VALUES (%s, '12a', %s, "
                     "'registered')", (oid, f"12A{tag()}"))
    for year, income in (("FY2022-23", 100), ("FY2023-24", None)):
        await db.execute("INSERT INTO org_financials (org_id, fiscal_year, total_income, is_audited) "
                         "VALUES (%s, %s, %s, true)", (oid, year, income))
    await db.execute("INSERT INTO documents (org_id, doc_type, source_url) VALUES (%s, 'audit_report', %s)",
                     (oid, f"https://zz-{tag()}.example.org/a.pdf"))

    fid = await funder(db, f"Zz Match Funder {tag()}", funder_type="csr_foundation", grant_size_min=1e5,
                       grant_size_max=1e6)
    await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES (%s, %s, 'registered'), "
                     "(%s, %s, 'funds')", (fid, bihar, fid, assam))
    await db.execute("INSERT INTO funder_tags (funder_id, tag_id) VALUES (%s, %s)", (fid, sub))
    await db.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, state_location_id) "
                     "VALUES (%s, 'footprint', 'FY2023-24', %s)", (fid, assam))
    spend = await one(db, "INSERT INTO funder_activity (funder_id, kind, fiscal_year, amount, domain_tag_id, "
                          "classified_by, partner_org_id, partner_name, project_name) VALUES (%s, 'spend', "
                          "'FY2023-24', 500, %s, 'report', %s, 'Zz', 'Skills') RETURNING id", fid, domain, oid)
    await db.execute("INSERT INTO documents (funder_id, doc_type, source_url, content_md) VALUES (%s, "
                     "'funder_eligibility', %s, %s)",
                     (fid, f"https://zz-{tag()}.example.org/policy", POLICY))
    other = await funder(db, f"Zz Other Funder {tag()}")
    return oid, fid, other, spend["id"], {"sub": sub, "assam": assam, "bihar": bihar}


async def test_both_sides_of_a_match_are_read_with_their_themes_places_and_bars(db):
    oid, fid, other, spend, ids = await _profiles(db)
    tax = await matching._taxonomy(db)

    org = await matching._org(db, oid, tax)
    assert org.location_ids == {ids["assam"]} and "population-women" in org.population
    assert "theme-skilling" in org.themes.themes and "domain-livelihoods" in org.themes.domains
    assert "csr-education-and-livelihoods" in org.themes.clauses
    assert [p.name for p in org.programs] == ["Skills", "Untagged"]
    assert org.identifiers["12a"][0].status == "registered"
    assert org.financials[0] == ("FY2023-24", True) and float(org.total_income) == 100
    assert org.doc_types == ["audit_report"] and [p.funder_id for p in org.partner_lines] == [fid]
    assert org.labels["population-women"]
    assert await matching._org(db, -1, tax) is None

    funders = {f.id: f for f in await matching._funders(db, [fid, other], tax)}
    f = funders[fid]
    assert f.registered_ids == {ids["bihar"]} and f.location_ids == {ids["assam"]}
    assert "theme-skilling" in f.themes.themes and "domain-health" in f.themes.domains
    assert f.spend == [(spend, "FY2023-24")]
    assert [text for _, text in f.bars] == ["Three years of accounts.", "Works in two states.", "Political bodies."]
    assert funders[other].spend == [] and funders[other].bars == []


async def test_load_reads_everything_in_one_read_only_transaction(db):
    oid, fid, _, _, _ = await _profiles(db)
    org, funders, places = await matching.load(_PoolOf(db), oid, [fid])
    assert org.id == oid and [f.id for f in funders] == [fid]
    assert places is not None


async def test_only_staff_and_the_orgs_stewards_and_admins_may_run(db):
    oid = await org(db, f"Zz Run Org {tag()}")
    people = {}
    for role in ("staff", "steward", "admin", "member", "stranger"):
        uid = uuid.uuid4()
        await db.execute("INSERT INTO users (id, email, is_staff) VALUES (%s, %s, %s)",
                         (uid, f"{role}-{uid.hex[:8]}@zz.test", role == "staff"))
        if role in ("steward", "admin", "member"):
            await db.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, %s)", (uid, oid, role))
        people[role] = uid
    pool = _PoolOf(db)
    allowed = {role: await matching.may_run(pool, uid, oid) for role, uid in people.items()}
    assert allowed == {"staff": True, "steward": True, "admin": True, "member": False, "stranger": False}
    assert not await matching.may_run(pool, None, oid)
