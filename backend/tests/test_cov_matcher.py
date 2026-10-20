"""resolve_funder / resolve_org on rows built here: which step resolves a name, and when a person must decide."""

from __future__ import annotations

import pytest

from app.ingest.matcher import resolve_funder, resolve_org
from tests.test_cov_promote import funder, org, tag

pytestmark = pytest.mark.integration
CIN = "L65920MH1994PLC080618"


async def test_a_cin_resolves_the_company_but_not_its_foundation(db):
    t = tag()
    company = await funder(db, f"Zz Cinco Bank Limited {t}", cin=CIN)
    assert (await resolve_funder(db, f"Zz Cinco Bank {t}", cin=CIN.lower())).entity_id == company
    found = await resolve_funder(db, f"Qq Cinco Welfare Foundation {tag()}", cin=CIN)
    assert found.method != "identifier" and found.entity_id != company


async def test_funder_alias_variant_website_and_boilerplate_steps(db):
    t = tag()
    aliased = await funder(db, f"Zz Long Formal Name {t}", aliases=[f"ZLF {t}"])
    assert (await resolve_funder(db, f"zlf {t}")).method == "alias"
    assert (await resolve_funder(db, f"Something Else Entirely {t} (ZLF {t})")).entity_id == aliased

    site = await funder(db, f"Zz Website Corp {t}", website=f"https://www.zz-site-{t}.example.org/home")
    hit = await resolve_funder(db, f"Zz Website Corporation {t}", website=f"http://zz-site-{t}.example.org")
    assert (hit.method, hit.entity_id) in (("website", site), ("boilerplate", site))

    plain = await funder(db, f"Zz Boiler Plate {t}")
    found = await resolve_funder(db, f"Zz Boiler Plate {t} Limited")
    assert (found.method, found.entity_id) == ("boilerplate", plain)


async def test_a_spelling_two_funders_share_resolves_neither(db):
    t = tag()
    await funder(db, f"Zz Twin One {t}", aliases=[f"Shared Zz {t}"])
    await funder(db, f"Zz Twin Two {t}", aliases=[f"Shared Zz {t}"])
    assert (await resolve_funder(db, f"Shared Zz {t}")).entity_id is None


async def test_a_company_and_its_foundation_sharing_a_site_do_not_merge(db):
    t = tag()
    await funder(db, f"Qq Sitey Industries {t}", website=f"https://qq-sitey-{t}.example.org")
    found = await resolve_funder(db, f"Zz Unrelated Welfare Trust {tag()}", website=f"https://qq-sitey-{t}.example.org")
    assert found.method != "website"


async def test_a_resembling_funder_is_proposed_not_resolved(db):
    t = tag()
    stored = await funder(db, f"Zqvortex Harmony Holdings {t}")
    found = await resolve_funder(db, f"Zqvortex Harmonia Holdings {t}")
    assert found.method == "trigram" and found.entity_id is None and found.candidates[0]["id"] == stored
    assert (await resolve_funder(db, f"Qqxyzzy Plover Wombat {tag()}")).method == "none"


async def test_org_identifier_name_alias_variant_and_website_steps(db):
    t = tag()
    by_id = await org(db, f"Zz Numbered Org {t}")
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) VALUES (%s, 'pan', %s, "
                     "'registered')", (by_id, f"PAN{t}"))
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) VALUES (%s, 'reg_no', %s, "
                     "'registered')", (by_id, f"REG{t}"))
    assert (await resolve_org(db, "anything", {"pan": f"pan{t}"})).entity_id == by_id
    assert (await resolve_org(db, f"Qq Other {tag()}", {"reg_no": f"REG{t}"})).method != "identifier"

    named = await org(db, f"Zz Named Org {t}", aliases=[f"ZNO {t}"])
    assert (await resolve_org(db, f"zz named org {t}")).method == "exact"
    assert (await resolve_org(db, f"ZNO {t}")).entity_id == named
    assert (await resolve_org(db, f"Something Long {t} (ZNO {t})")).entity_id == named

    site = await org(db, f"Zz Site Org {t}", website=f"https://zz-orgsite-{t}.example.org")
    assert (await resolve_org(db, f"Qq Different {tag()}", website=f"zz-orgsite-{t}.example.org")).entity_id == site


async def test_org_normalised_name_boilerplate_shared_and_trigram(db):
    t = tag()
    dotted = await org(db, f"Zz Seva-Kendra {t}")
    assert (await resolve_org(db, f"Zz Seva Kendra {t}")).entity_id == dotted

    plain = await org(db, f"Zz Gramin Vikas {t}")
    found = await resolve_org(db, f"Zz Gramin Vikas {t} Society")
    assert (found.method, found.entity_id) == ("boilerplate", plain)

    await org(db, f"Zz Pair A {t}", aliases=[f"Zz Same Spelling {t}"])
    await org(db, f"Zz Pair B {t}", aliases=[f"Zz Same Spelling {t}"])
    assert (await resolve_org(db, f"Zz Same Spelling {t}")).entity_id is None

    near = await org(db, f"Zqvortex Harmony Sanstha {t}")
    found = await resolve_org(db, f"Zqvortex Harmonia Sanstha {t}")
    assert found.method == "trigram" and found.candidates[0]["id"] == near
    assert (await resolve_org(db, f"Qqxyzzy Plover Wombat {tag()}")).method == "none"
