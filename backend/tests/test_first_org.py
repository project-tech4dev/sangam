"""Funder Match and RFP Watch given no org: as the caller, they read the caller's first organisation by name."""

from __future__ import annotations

import json
import uuid

import pytest

from app.db.pool import set_caller
from app.repositories import funder_matches, rfps
from tests.test_cov_promote import funder, one, org, tag
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration


async def _steward_of_two(db) -> tuple[dict, dict, str]:
    """Orgs Zz A and Zz B, a run on A, and a steward of both: only a steward can hold two orgs."""
    t = tag()
    first = await org(db, f"Zz A {t}")
    second = await org(db, f"Zz B {t}")
    auth = uuid.uuid4()
    uid = (await one(db, "INSERT INTO users (email, auth_user_id) VALUES (%s, %s) RETURNING id",
                     f"m-{t}@zz.test", auth))["id"]
    for oid in (second, first):
        await db.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'steward')", (uid, oid))
    fid = await funder(db, f"Zz Funder {t}")
    await db.execute(
        """INSERT INTO funder_matches (run_id, org_id, funder_id, run_at, rubric_version, score, card)
           VALUES (%s, %s, %s, now(), 'match-v2', 80, '{}')""", (uuid.uuid4(), first, fid))
    slugs = await (await db.execute("SELECT id, slug FROM orgs WHERE id IN (%s, %s)", (first, second))).fetchall()
    by_id = {r["id"]: r for r in slugs}
    return by_id[first], by_id[second], json.dumps({"sub": str(auth), "role": "authenticated"})


async def test_no_org_reads_the_callers_first_by_name_in_one_connection(db):
    first, second, claims = await _steward_of_two(db)
    await set_caller(db, "authenticated", claims)
    pool = _PoolOf(db)

    found, run, rows = await funder_matches.read_latest(pool, None)
    assert found["slug"] == first["slug"] and found["may_read"] and found["may_run"]
    assert run["funders_checked"] == 1 and run["earlier_runs"] == 0 and [r["score"] for r in rows] == [80]

    named, run, rows = await funder_matches.read_latest(pool, second["slug"])
    assert named["slug"] == second["slug"] and run is None and rows == []

    assert (await rfps.feed(pool, None))["slug"] == first["slug"]


async def test_no_org_and_no_membership_finds_nothing(db):
    auth = uuid.uuid4()
    await db.execute("INSERT INTO users (email, auth_user_id) VALUES (%s, %s)", (f"n-{tag()}@zz.test", auth))
    await set_caller(db, "authenticated", json.dumps({"sub": str(auth), "role": "authenticated"}))
    pool = _PoolOf(db)
    assert await funder_matches.read_latest(pool, None) == (None, None, [])
    assert await rfps.feed(pool, None) is None
