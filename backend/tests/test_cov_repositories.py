"""Small REST repositories on rows built here: filters, the detail lookups, and their None paths."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest

from app.repositories import contacts, funders, meta, orgs, rfps, users
from tests.test_cov_promote import funder, one, org, tag
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration


class _SavepointPool(_PoolOf):
    """Each connection in a savepoint, so a refused insert does not abort the test's transaction."""

    def connection(self):
        conn = self._conn

        @asynccontextmanager
        async def held():
            async with conn.transaction():
                yield conn
        return held()


async def _tag_id(db, slug: str) -> int:
    row = await one(db, "SELECT id FROM tags WHERE slug = %s", slug)
    if row is None:
        pytest.skip(f"taxonomy not seeded ({slug})")
    return row["id"]


async def test_resolve_auth_user_finds_links_creates_and_refuses(db):
    pool = _PoolOf(db)
    t = tag()
    auth, email = uuid.uuid4(), f"new-{t}@zz.test"
    made = await users.resolve_auth_user(pool, auth_user_id=auth, email=email, display_name="Zz")
    assert made["is_staff"] is False
    again = await users.resolve_auth_user(pool, auth_user_id=auth, email=f"moved-{t}@zz.test", display_name=None)
    assert again["id"] == made["id"]
    assert (await one(db, "SELECT email FROM users WHERE id = %s", made["id"]))["email"] == f"moved-{t}@zz.test"

    # Staff pre-created this row by email; signing in links it rather than making a twin.
    pre = (await one(db, "INSERT INTO users (email, is_staff) VALUES (%s, true) RETURNING id", f"pre-{t}@zz.test"))["id"]
    linked = await users.resolve_auth_user(pool, auth_user_id=uuid.uuid4(), email=f"pre-{t}@zz.test",
                                           display_name="Pre")
    assert linked == {"id": pre, "is_staff": True}

    with pytest.raises(users.EmailTakenError) as err:
        await users.resolve_auth_user(pool, auth_user_id=uuid.uuid4(), email=f"moved-{t}@zz.test", display_name=None)
    assert err.value.linked_auth_user_id == auth


async def test_contacts_filter_create_update_and_a_missing_parent(db):
    pool = _PoolOf(db)
    fid = await funder(db, f"Zz Contact Funder {tag()}")
    slug = (await one(db, "SELECT slug FROM funders WHERE id = %s", fid))["slug"]
    base = {"org_id": None, "funder_id": fid, "role": "CSR head", "email": None, "phone": None, "notes": None}
    a = await contacts.create_contact(pool, {**base, "name": "Zz Asha", "kind": "grants", "verified": True})
    await contacts.create_contact(pool, {**base, "name": "Zz Bina", "kind": "programme", "verified": False})

    found, total = await contacts.list_contacts(pool, limit=10, offset=0, funder=slug, kind="grants")
    assert total == 1 and found[0]["name"] == "Zz Asha" and found[0]["source_name"] == "manual"
    _, total = await contacts.list_contacts(pool, limit=10, offset=0, funder=str(fid), verified=False)
    assert total == 1
    assert await contacts.list_contacts(pool, limit=10, offset=0, funder="zz-no-such-funder") == ([], 0)

    await db.execute("UPDATE contacts SET source_type = 'funder', evidence = 'evidenced' WHERE id = %s", (a["id"],))
    edited = await contacts.update_contact(pool, a["id"], {"phone": "12345", "ignored": "x"})
    assert edited["phone"] == "12345" and edited["source_type"] is None and edited["evidence"] is None
    assert (await contacts.update_contact(pool, a["id"], {}))["id"] == a["id"]
    assert await contacts.get_contact(pool, -1) is None

    missing = await contacts.create_contact(_SavepointPool(db), {**base, "funder_id": -1, "name": "Zz Gone",
                                                                 "kind": "other", "verified": False})
    assert missing is None


async def test_orgs_list_filters_and_the_detail_with_its_parts(db):
    pool = _PoolOf(db)
    t = tag()
    district = await one(db, "SELECT d.id, d.name, s.name AS state FROM locations d JOIN locations s "
                             "ON s.id = d.parent_id WHERE d.kind = 'district' AND s.name = 'Assam' LIMIT 1")
    if district is None:
        pytest.skip("geography not seeded")
    women = await _tag_id(db, "population-women")
    oid = await org(db, f"Zz Listed Org {t}", registered_location_id=district["id"])
    await db.execute("INSERT INTO org_tags (org_id, tag_id) VALUES (%s, %s)", (oid, women))
    await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) VALUES (%s, 'darpan', %s, "
                     "'registered')", (oid, f"AS/{t}"))
    await db.execute("INSERT INTO org_locations (org_id, location_id) VALUES (%s, %s)", (oid, district["id"]))

    found, total = await orgs.list_orgs(pool, limit=5, offset=0, q=f"Listed Org {t}", state="assam",
                                        district=district["name"].lower(), tag="population-women")
    assert total == 1 and found[0]["darpan_id"] == f"AS/{t}" and found[0]["state"] == "Assam"
    assert (await orgs.list_orgs(pool, limit=5, offset=0, q=f"Listed Org {t}", state="Bihar"))[1] == 0

    detail = await orgs.get_org(pool, str(oid))
    assert detail["district"] == district["name"] and detail["identifiers"][0]["id_type"] == "darpan"
    assert [x["slug"] for x in detail["tags"]] == ["population-women"] and len(detail["locations"]) == 1
    assert detail["contacts"] == []
    assert await orgs.get_org(pool, "zz-no-such-org") is None


async def test_funders_list_detail_scores_and_name_variants(db):
    pool = _PoolOf(db)
    t = tag()
    sub = await _tag_id(db, "sub_theme-vocational-foundational")
    fid = await funder(db, f"The Zz Variant Giver {t} Pvt Ltd", aliases=[f"ZVG {t}"], section_135_bound=True)
    await db.execute("INSERT INTO funder_tags (funder_id, tag_id) VALUES (%s, %s)", (fid, sub))
    assam = await one(db, "SELECT id FROM locations WHERE kind = 'state' AND name = 'Assam'")
    await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES (%s, %s, 'funds')",
                     (fid, assam["id"]))

    own = (await one(db, "INSERT INTO tags (slug, label) VALUES (%s, 'Zz sector') RETURNING id", f"zz-sector-{t}"))["id"]
    await db.execute("INSERT INTO funder_tags (funder_id, tag_id) VALUES (%s, %s)", (fid, own))
    (mine,), total = await funders.list_funders(pool, limit=5, offset=0, tag=f"zz-sector-{t}", section_135=True)
    assert total == 1 and mine["id"] == fid and "Zz sector" in mine["focus_sectors"]
    assert await funders.list_funders(pool, limit=5, offset=0, tag=f"zz-sector-{t}", section_135=False) == ([], 0)
    assert mine["geographies"] == ["Assam"] and mine["latest_scores"] == {}

    detail = await funders.get_funder(pool, str(fid))
    assert detail["locations"][0]["role"] == "funds" and detail["tags"] and detail["contacts"] == []
    assert await funders.get_funder(pool, "zz-no-such-funder") is None
    assert await funders.funder_scores(pool, fid) == []

    by_name = await funders.name_variants(pool, match=f"zz variant giver {t}")
    by_alias = await funders.name_variants(pool, match=f"zvg {t}")
    assert [r["aliases"] for r in by_name] == [[f"ZVG {t}"]] and len(by_alias) == 1


async def test_meta_tags_locations_and_stats(db):
    pool = _PoolOf(db)
    found, total = await meta.list_tags(pool, limit=5, offset=0, kind="domain", q="livelihood")
    assert total >= 1 and all(r["kind"] == "domain" for r in found)
    assam = await one(db, "SELECT id FROM locations WHERE kind = 'state' AND name = 'Assam'")
    places, _ = await meta.list_locations(pool, limit=3, offset=0, kind="district", parent=assam["id"])
    assert places and all(p["parent_name"] == "Assam" for p in places)
    before = await meta.stats(pool)
    await org(db, f"Zz Stats Org {tag()}")
    assert (await meta.stats(pool))["orgs"] == before["orgs"] + 1


async def test_open_calls_are_flagged_for_orgs_sharing_a_domain_and_fed_back(db):
    pool = _PoolOf(db)
    sub = await _tag_id(db, "sub_theme-vocational-foundational")
    health = await _tag_id(db, "domain-health")
    oid = await org(db, f"Zz Feed Org {tag()}")
    await db.execute("INSERT INTO org_tags (org_id, tag_id) VALUES (%s, %s)", (oid, sub))
    uid = (await one(db, "INSERT INTO users (email) VALUES (%s) RETURNING id", f"m-{tag()}@zz.test"))["id"]
    await db.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'member')", (uid, oid))
    fid = await funder(db, f"Zz Caller {tag()}")
    rfp = (await one(db, "INSERT INTO rfps (funder_id, title, status, deadline) VALUES (%s, 'Zz skilling call', "
                         "'open', current_date + 30) RETURNING id", fid))["id"]
    other = (await one(db, "INSERT INTO rfps (funder_id, title, status, deadline) VALUES (%s, 'Zz health call', "
                           "'open', current_date + 30) RETURNING id", fid))["id"]
    await db.execute("INSERT INTO rfp_tags (rfp_id, tag_id) VALUES (%s, %s), (%s, %s)", (rfp, sub, other, health))

    flagged = await rfps.flag_matches(pool)
    assert flagged["added"] >= 1
    assert (await rfps.flag_matches(pool))["added"] == 0
    matches = await rfps.list_matches(pool, rfp)
    assert oid in [m["org_id"] for m in matches]
    assert oid not in [m["org_id"] for m in await rfps.list_matches(pool, other)]

    slug = (await one(db, "SELECT slug FROM orgs WHERE id = %s", oid))["slug"]
    fed = await rfps.feed(pool, slug)
    assert any("Livelihood" in d for d in fed["domains"])
    item, = [i for i in fed["items"] if i["rfp_id"] in (rfp, other)]
    assert item["rfp_id"] == rfp and "Livelihood" in item["themes"][0]
    assert await rfps.feed(pool, "zz-no-such-org") is None

    done = await rfps.update_match(pool, rfp, oid, status="dismissed", match_notes=None, matched_by="zz")
    assert done["status"] == "dismissed"
    assert rfp not in [i["rfp_id"] for i in (await rfps.feed(pool, slug))["items"]]
    assert (await rfps.get_rfp(pool, rfp))["funder_name"].startswith("Zz Caller")
    listed, total = await rfps.list_rfps(pool, limit=50, offset=0, status="open", tag="domain-health")
    assert other in [r["id"] for r in listed] and rfp not in [r["id"] for r in listed] and total >= 1


def test_themes_name_a_bare_domain_only_when_nothing_under_it_is_tagged():
    pairs = [["Livelihoods", "Skilling"], ["Livelihoods", None], ["Health", None], ["Livelihoods", "Skilling"]]
    assert rfps._themes(pairs) == ["Livelihoods · Skilling", "Health"]
