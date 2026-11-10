"""Profile facts against a real schema: what a public profile serves, and the private rows it never does."""

import json
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.db.pool import CallerPool
from app.ingest.source_guards import is_private_source
from app.repositories import partner_groups, registry
from app.repositories import profile_facts as repo
from app.repositories.public_sql import is_private_url
from app.schemas.profiles import FunderProfile, OrgProfile
from app.schemas.registry import RegistryOut
from tests.test_rls import DSN

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool():
    p = AsyncConnectionPool(DSN, kwargs={"row_factory": dict_row, "autocommit": True}, open=False)
    try:
        await p.open(wait=True, timeout=3)
    except Exception:  # noqa: BLE001 - any failure to connect means no scratch database here
        pytest.skip("Postgres not reachable")
    yield p
    await p.close()


async def _one(c, sql, params=()):
    return (await (await c.execute(sql + " RETURNING id", params)).fetchone())["id"]


async def _world(pool):
    t = uuid4().hex[:8]
    async with pool.connection() as c:
        state = await _one(c, "INSERT INTO locations (kind, name) VALUES ('state', %s)", (f"State {t}",))
        d1 = await _one(c, "INSERT INTO locations (kind, name, parent_id) VALUES ('district', %s, %s)",
                        (f"Alpha {t}", state))
        d2 = await _one(c, "INSERT INTO locations (kind, name, parent_id) VALUES ('district', %s, %s)",
                        (f"Beta {t}", state))
        d3 = await _one(c, "INSERT INTO locations (kind, name, parent_id) VALUES ('district', %s, %s)",
                        (f"Gamma {t}", state))
        org = await _one(c, "INSERT INTO orgs (slug, name) VALUES (%s, %s)", (f"o-{t}", f"Org {t}"))
        funder = await _one(c, "INSERT INTO funders (slug, name) VALUES (%s, %s)", (f"f-{t}", f"Funder {t}"))
        prog = await _one(c, "INSERT INTO programs (org_id, name, kind) VALUES (%s, 'Water', 'programme')", (org,))
        phase = await _one(c, "INSERT INTO programs (org_id, name, kind, parent_id) VALUES (%s, 'Phase 1', 'phase', %s)",
                           (org, prog))
        fprog = await _one(c, "INSERT INTO programs (funder_id, name, kind) VALUES (%s, 'SLP', 'programme')",
                           (funder,))
        theme = await _one(c, "INSERT INTO tags (slug, label, kind) VALUES (%s, 'Livelihoods', 'theme')",
                           (f"th-{t}",))
        sdg = await _one(c, "INSERT INTO tags (slug, label, kind, code) VALUES (%s, 'No poverty', 'sdg', '1')",
                         (f"sdg-{t}",))
        await c.execute("INSERT INTO tag_links (tag_id, linked_tag_id) VALUES (%s, %s)", (theme, sdg))
        await c.execute("INSERT INTO org_tags (org_id, tag_id, role, note) VALUES (%s, %s, 'primary', 'mission')",
                        (org, theme))
        await c.execute("INSERT INTO program_tags (program_id, tag_id, role, note) VALUES (%s, %s, 'primary', 'p')",
                        (prog, theme))
        await c.execute("INSERT INTO org_locations (org_id, location_id, role, note, program_id) "
                        "VALUES (%s, %s, 'operates', 'SHGs', %s)", (org, d1, prog))
        await c.execute("INSERT INTO contacts (org_id, name, is_public) VALUES (%s, 'Public', true), "
                        "(%s, 'Private', false)", (org, org))
        await c.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, is_public) "
                        "VALUES (%s, 'pan', %s, 'registered', false), (%s, 'csr1', NULL, 'not_available', true)",
                        (org, f"PAN{t}", org))
        await c.execute("INSERT INTO metrics (org_id, program_id, name, value) VALUES (%s, %s, 'Families', 10)",
                        (org, prog))
        await c.execute("INSERT INTO org_financials (org_id, fiscal_year, total_income) VALUES (%s, 'FY2023-24', 5)",
                        (org,))
        pub = await _one(c, "INSERT INTO documents (org_id, title, is_public) VALUES (%s, 'Annual report', true)",
                         (org,))
        await _one(c, "INSERT INTO documents (org_id, title, is_public) VALUES (%s, 'Vault file', false)", (org,))
        fdoc = await _one(c, "INSERT INTO documents (funder_id, title, is_public) VALUES (%s, 'Funder AR', true)",
                          (funder,))
        await c.execute("INSERT INTO document_links (document_id, org_id, program_id, fiscal_year, pages) "
                        "VALUES (%s, %s, %s, 'FY2024-25', '{p.3}'), (%s, %s, NULL, NULL, '{p.40}')",
                        (pub, org, prog, fdoc, org))
        await c.execute("INSERT INTO documents (funder_id, title, doc_type, content_md, is_public) "
                        "VALUES (%s, 'Eligibility', 'funder_eligibility', '- NGOs only', true)", (funder,))
        for kind, loc, public in [("footprint", d1, True), ("footprint", d2, True), ("footprint", d3, False)]:
            await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, location_id, program_id, "
                            "is_public) VALUES (%s, %s, 'FY2023-24', %s, %s, %s)", (funder, kind, loc, fprog, public))
        await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, amount, is_public) "
                        "VALUES (%s, 'programme', 'FY2024-25', %s, 100, true), "
                        "(%s, 'programme', 'FY2023-24', %s, 99, false)", (funder, fprog, funder, fprog))
        await c.execute("INSERT INTO funder_csr_years (funder_id, fiscal_year, total_spent) VALUES (%s, 'FY2024-25', 7)",
                        (funder,))
        await c.execute("INSERT INTO funder_locations (funder_id, location_id, role, note) "
                        "VALUES (%s, %s, 'priority', 'tribal belt')", (funder, d2))
        await c.execute("INSERT INTO rfps (funder_id, title, status) VALUES (%s, 'Open call', 'open'), "
                        "(%s, 'Old call', 'closed')", (funder, funder))
        await c.execute("INSERT INTO contacts (funder_id, name, is_public) VALUES (%s, 'Staffer', false)", (funder,))
    return {"t": t, "org": org, "funder": funder, "prog": prog, "phase": phase, "state": f"State {t}"}


async def test_org_facts(pool):
    w = await _world(pool)
    facts = await repo.org_facts(pool, pool, f"o-{w['t']}")
    assert [c.name for c in facts.org.contacts] == ["Public"]
    ids = {i.id_type: i for i in facts.org.identifiers}
    assert ids["pan"].id_value is None and ids["pan"].number_withheld
    assert not ids["csr1"].number_withheld
    # Its own public document and the funder's that backs one of its facts; never the vault file.
    assert {d.title for d in facts.documents} == {"Annual report", "Funder AR"}
    links = {d.title: d.links for d in facts.documents}
    assert links["Annual report"][0].pages == ["p.3"] and links["Annual report"][0].program_name == "Water"
    place = facts.places[0]
    assert (place.state, place.program_name, place.note) == (w["state"], "Water", "SHGs")
    progs = {p.name: p for p in facts.programs}
    assert progs["Phase 1"].parent_id == w["prog"]
    assert progs["Water"].metrics[0].name == "Families" and progs["Water"].tags[0].note == "p"
    assert facts.tags[0].note == "mission"
    assert [(s.code, s.label) for s in facts.sdgs] == [("1", "No poverty")]
    assert facts.financials[0].fiscal_year == "FY2023-24"
    assert facts.hidden_contacts == 1
    assert await repo.org_facts(pool, pool, f"nope-{w['t']}") is None


async def test_funder_facts(pool):
    w = await _world(pool)
    facts = await repo.funder_facts(pool, pool, f"f-{w['t']}")
    assert facts.funder.contacts == [] and facts.hidden_contacts == 1
    assert len(facts.footprint) == 1 and facts.footprint[0].state == w["state"] and facts.footprint[0].districts == 2
    assert [s.amount for s in facts.spend] == [100]
    assert facts.csr_years[0].total_spent == 7
    assert facts.stated[0].note == "tribal belt" and facts.stated[0].state == w["state"]
    assert [e.content_md for e in facts.eligibility] == ["- NGOs only"]
    assert [d.title for d in facts.documents] == ["Funder AR"]
    assert [r.title for r in facts.open_calls] == ["Open call"]


async def test_research_is_counted_without_content(pool):
    w = await _world(pool)
    async with pool.connection() as c:
        for day, urls in [("2026-10-01", ["https://give.do/a", "https://kabil.org", "https://s.sangam.invalid/x"]),
                          ("2026-10-05", ["https://give.do/a", "https://rcrc.in/p"])]:
            await c.execute(
                "INSERT INTO entity_research (entity_name, entity_kind, slug, status, summary, sources_read, "
                "resolved_org_id, researched_on) VALUES (%s, 'org', %s, 'partial', 's', %s, %s, %s)",
                (f"Org {w['t']}", f"o-{w['t']}", urls, w["org"], day))
        await c.execute(
            "INSERT INTO entity_research (entity_name, entity_kind, slug, status, summary, resolved_org_id, "
            "researched_on) VALUES ('x', 'org', %s, 'wrong_entity', 's', %s, '2026-10-09')",
            (f"o-{w['t']}", w["org"]))
    research = (await repo.org_facts(pool, pool, f"o-{w['t']}")).research
    assert research.runs == 2 and str(research.latest) == "2026-10-05"
    assert {s.url: str(s.first_read) for s in research.sources} == {
        "https://give.do/a": "2026-10-01", "https://kabil.org": "2026-10-01", "https://rcrc.in/p": "2026-10-05"}
    rows = {r["slug"]: r for r in await registry.registry_rows(pool, pool)}
    counts = await registry.research_counts(pool, [("org", w["org"], f"o-{w['t']}")])
    assert counts[("org", w["org"])]["runs"] == 2 and rows[f"o-{w['t']}"]["slug"] == f"o-{w['t']}"


async def test_registry_rows_read_what_the_list_filters_on(pool):
    w = await _world(pool)
    async with pool.connection() as c:
        await c.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, is_public) VALUES "
                        "(%s, '12a', %s, 'registered', true), (%s, '80g', %s, 'registered', false)",
                        (w["org"], f"A{w['t']}", w["org"], f"G{w['t']}"))
        await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
                        "is_public) VALUES (%s, 'partner', 'FY2024-25', 'Org', %s, true)", (w["funder"], w["org"]))
        await c.execute("INSERT INTO funder_csr_years (funder_id, fiscal_year, prescribed_csr) "
                        "VALUES (%s, 'FY2023-24', 9)", (w["funder"],))
    rows = {r["slug"]: r for r in await registry.registry_rows(pool, pool)}
    org, funder = rows[f"o-{w['t']}"], rows[f"f-{w['t']}"]
    assert org["states"] == [w["state"]] and org["place"] == f"Alpha {w['t']}, {w['state']}"
    assert org["themes"] == [{"label": "Livelihoods", "domain": None}] and org["sdgs"] == ["1"]
    # A private 80G is still on file.
    assert org["has_12a_80g"] and not org["csr1"] and org["partners"] == 1
    assert "water" in org["search"] and f"funder {w['t']}" in org["search"]
    assert funder["states"] == [w["state"]] and funder["open_call"] and funder["partners"] == 1
    # The latest year with a prescribed figure, not the latest year on file.
    assert (funder["csr_year"], funder["csr_prescribed"]) == ("FY2023-24", 9)


async def test_private_url_is_the_same_rule_in_sql_and_python(pool):
    urls = ["https://staff.sangam.invalid/a", "HTTP://X.SANGAM.INVALID", "https://sangam.invalid",
            "https://user:pw@vault.sangam.invalid:8443/x?y", "https://sangam.invalid./x",
            "https://notsangam.invalid/x", "https://sangam.invalid.example.com/x", "https://give.do/a",
            "http://example.org/?ref=sangam.invalid", "mailto:a@b.org"]
    async with pool.connection() as c:
        got = {r["u"]: r["p"] for r in await (await c.execute(
            f"SELECT u, {is_private_url('u')} AS p FROM unnest(%(urls)s::text[]) u", {"urls": urls})).fetchall()}
    assert got == {u: is_private_source(u) for u in urls}
    async with pool.connection() as c:
        bare = (await (await c.execute(f"SELECT {is_private_url(chr(39) + 'x.sangam.invalid/y' + chr(39))} AS p"))
                .fetchone())["p"]
    assert bare  # stricter than Python for a scheme-less private host, never looser


PRIVATE = "https://sheet.sangam.invalid/staff/{t}"
PUBLIC = "https://public.example.org/{t}"


async def test_no_private_link_reaches_a_public_response(pool):
    """Every URL column a profile or the list selects, set private on one row and public on its twin."""
    w = await _world(pool)
    t, org, funder = w["t"], w["org"], w["funder"]
    priv, pub = PRIVATE.format(t=t), PUBLIC.format(t=t)
    async with pool.connection() as c:
        await c.execute("UPDATE orgs SET website = %s, source_url = %s, source_name = 'Staff sheet' WHERE id = %s",
                        (priv, priv, org))
        await c.execute("UPDATE funders SET website = %s, source_url = %s, profile = %s WHERE id = %s",
                        (pub, priv, json.dumps({"funding_trend": f"See {priv}"}), funder))
        for table, owner in [("programs", "org_id"), ("contacts", "org_id"), ("metrics", "org_id")]:
            extra = {"contacts": ", is_public", "metrics": ", value"}.get(table, "")
            vals = {"contacts": ", true", "metrics": ", 1"}.get(table, "")
            for i, url in enumerate((priv, pub)):
                await c.execute(f"INSERT INTO {table} ({owner}, name, source_url, source_name{extra}) "
                                f"VALUES (%s, %s, %s, 'Src {i}'{vals})", (org, f"{table}-{i}-{t}", url))
        await c.execute("UPDATE org_locations SET source_url = %s, source_name = 'Sheet', note = %s WHERE org_id = %s",
                        (priv, f"read in {priv}", org))
        await c.execute("UPDATE org_identifiers SET source_url = %s, notes = %s WHERE org_id = %s",
                        (priv, f"per {priv}", org))
        await c.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, source_url) "
                        "VALUES (%s, 'fcra', %s, 'registered', %s)", (org, f"F{t}", pub))
        await c.execute("INSERT INTO org_financials (org_id, fiscal_year, source_url) VALUES (%s, 'FY2022-23', %s), "
                        "(%s, 'FY2021-22', %s)", (org, priv, org, pub))
        await c.execute("INSERT INTO documents (org_id, title, source_url, is_public) VALUES (%s, 'P', %s, true), "
                        "(%s, 'Q', %s, true)", (org, priv, org, pub))
        await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
                        "source_url, notes, is_public) VALUES (%s, 'partner', 'FY2024-25', 'Org', %s, %s, %s, true), "
                        "(%s, 'partner', 'FY2023-24', 'Org', %s, %s, NULL, true)",
                        (funder, org, priv, f"sheet {priv}", funder, org, pub))
        await c.execute("UPDATE funder_activity SET source_url = %s WHERE funder_id = %s AND kind <> 'partner'",
                        (priv, funder))
        await c.execute("INSERT INTO funder_csr_years (funder_id, fiscal_year, source_url) VALUES (%s, 'FY2020-21', %s)",
                        (funder, priv))
        await c.execute("UPDATE funder_locations SET source_url = %s WHERE funder_id = %s", (priv, funder))
        await c.execute("UPDATE rfps SET url = %s, source_url = %s WHERE funder_id = %s", (priv, priv, funder))
        await c.execute("UPDATE documents SET source_url = %s WHERE funder_id = %s", (priv, funder))
        await c.execute("INSERT INTO entity_research (entity_name, entity_kind, slug, status, summary, sources_read, "
                        "resolved_org_id) VALUES ('x', 'org', %s, 'partial', 's', %s, %s)",
                        (f"o-{t}", [priv, pub], org))
    org_body = OrgProfile(**(await repo.org_facts(pool, pool, f"o-{t}")).model_dump()).model_dump_json()
    funder_body = FunderProfile(**(await repo.funder_facts(pool, pool, f"f-{t}")).model_dump()).model_dump_json()
    page = await partner_groups.entity_groups(pool, "funder", f"f-{t}", cursor=None, limit=20)
    reg = RegistryOut.model_validate({"rows": await registry.registry_rows(pool, pool)}).model_dump_json()
    everything = org_body + funder_body + json.dumps(page, default=str) + reg
    assert "sangam.invalid" not in everything
    # The public twin of each row is still there: the rule drops only what it must.
    assert org_body.count(pub) >= 7 and funder_body.count(pub) >= 2 and pub in json.dumps(page, default=str)


async def _staff(pool, tag: str) -> CallerPool:
    sub = str(uuid4())
    async with pool.connection() as c:
        await c.execute("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true)",
                        (f"s-{tag}@profile.test", sub))
    return CallerPool(pool, role="authenticated", claims=json.dumps({"sub": sub}))


async def test_every_viewer_reads_the_same_registrations_and_filters(pool):
    w = await _world(pool)
    anon = CallerPool(pool, role="anon", claims="")
    staff = await _staff(pool, w["t"])
    pages = [await repo.org_facts(viewer, pool, f"o-{w['t']}") for viewer in (anon, staff)]
    assert pages[0].org.identifiers == pages[1].org.identifiers
    assert pages[0].org.contacts == pages[1].org.contacts and pages[0].hidden_contacts == pages[1].hidden_contacts
    assert {i.id_type for i in pages[0].org.identifiers} == {"pan", "csr1"}  # the private PAN is on file for anon too
    lists = [{r["slug"]: r for r in await registry.registry_rows(viewer, pool)}[f"o-{w['t']}"] for viewer in (anon, staff)]
    assert lists[0] == lists[1]


async def test_partners_page_by_partner_with_the_true_total(pool):
    w = await _world(pool)
    async with pool.connection() as c:
        for i in range(25):
            await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, is_public) "
                            "VALUES (%s, 'partner', %s, %s, true)", (w["funder"], f"FY20{10 + i}-{11 + i}", f"P{i:02}"))
        # The same partner under another spelling folds into one group; a private line never counts.
        await c.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, is_public) "
                        "VALUES (%s, 'partner', 'FY2009-10', ' p00 ', true), (%s, 'partner', 'FY2009-10', 'Secret', false)",
                        (w["funder"], w["funder"]))
    first = await partner_groups.entity_groups(pool, "funder", f"f-{w['t']}", cursor=None, limit=20)
    assert first["total"] == 25 and len(first["groups"]) == 20 and first["next_cursor"]
    assert first["groups"][0]["name"] == "P24"  # newest first
    second = await partner_groups.entity_groups(pool, "funder", f"f-{w['t']}", cursor=first["next_cursor"], limit=20)
    assert len(second["groups"]) == 5 and second["next_cursor"] is None
    p00 = next(g for g in second["groups"] if g["key"] == "np00")
    assert len(p00["lines"]) == 2
    with pytest.raises(ValueError):
        await partner_groups.entity_groups(pool, "funder", f"f-{w['t']}", cursor="bm90IGEgbGlzdA==", limit=20)


async def test_story_counts_and_channel_are_decided_in_sql(pool):
    w = await _world(pool)
    async with pool.connection() as c:
        for kind, src in [("social", "LinkedIn"), ("social", "Instagram"), ("press", "online news")]:
            s = (await (await c.execute(
                "INSERT INTO news_stories (headline, topic, is_news, published_on) VALUES (%s, 'other', true, "
                "'2026-08-04') RETURNING id", (f"{kind} {w['t']}",))).fetchone())["id"]
            link = (await (await c.execute(
                "INSERT INTO news_links (url, host, source_type, story_id) VALUES (%s, 'h', %s, %s) RETURNING id",
                (f"https://h.example/{s}", src, s))).fetchone())["id"]
            await c.execute("UPDATE news_stories SET main_link_id = %s WHERE id = %s", (link, s))
            await c.execute("INSERT INTO news_story_entities (story_id, org_id, match, confidence, visibility) "
                            "VALUES (%s, %s, 0.9, 0.9, 'public')", (s, w["org"]))
    facts = await repo.org_facts(pool, pool, f"o-{w['t']}")
    assert (facts.stories.press, facts.stories.social) == (1, 2)
    row = {r["slug"]: r for r in await registry.registry_rows(pool, pool)}[f"o-{w['t']}"]
    assert (row["press"], row["social"]) == (1, 2)
    from app.repositories import news_stories

    page = await news_stories.entity_news(pool, kind="org", slug=f"o-{w['t']}", cursor=None, limit=10)
    assert sorted(s["channel"] for s in page["items"]) == ["press", "social", "social"]
