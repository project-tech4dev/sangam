from __future__ import annotations

from collections import defaultdict

from psycopg_pool import AsyncConnectionPool

from app.repositories.funder_matches import FIRST_ORG

BASE = """
SELECT r.*, f.name AS funder_name, COUNT(*) OVER () AS total
FROM rfps r
LEFT JOIN funders f ON f.id = r.funder_id
"""


async def list_rfps(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    status: str | None = None, deadline_before: str | None = None,
                    tag: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
    WHERE (%(status)s::text IS NULL OR r.status = %(status)s)
      AND (%(deadline_before)s::date IS NULL OR r.deadline <= %(deadline_before)s::date)
      AND (%(tag)s::text IS NULL OR EXISTS (
            SELECT 1 FROM rfp_tags rt JOIN tags tg ON tg.id = rt.tag_id
            WHERE rt.rfp_id = r.id AND (tg.slug = %(tag)s OR tg.label ILIKE %(tag)s)))
    ORDER BY r.deadline ASC NULLS LAST, r.id
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "status": status,
              "deadline_before": deadline_before, "tag": tag}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_rfp(pool: AsyncConnectionPool, rfp_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (await conn.execute(BASE + " WHERE r.id = %s", (rfp_id,))).fetchone()


async def list_matches(pool: AsyncConnectionPool, rfp_id: int) -> list[dict]:
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """
                SELECT m.*, o.name AS org_name
                FROM rfp_matches m JOIN orgs o ON o.id = m.org_id
                WHERE m.rfp_id = %s
                ORDER BY m.match_score DESC NULLS LAST
                """,
                (rfp_id,),
            )
        ).fetchall()


async def update_match(pool: AsyncConnectionPool, rfp_id: int, org_id: int, *,
                       status: str, match_notes: str | None, matched_by: str) -> dict | None:
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """
                UPDATE rfp_matches
                SET status = %s, match_notes = COALESCE(%s, match_notes), matched_by = %s
                WHERE rfp_id = %s AND org_id = %s
                RETURNING *
                """,
                (status, match_notes, matched_by, rfp_id, org_id),
            )
        ).fetchone()


# Every theme tag with the domain it rolls up to, and each org's domains through its own and its programmes' tags.
DOMAINS = """
WITH RECURSIVE up(tag_id, at) AS (
  SELECT id, id FROM tags WHERE kind IN ('domain', 'theme', 'sub_theme')
  UNION
  SELECT up.tag_id, t.parent_id FROM up JOIN tags t ON t.id = up.at WHERE t.parent_id IS NOT NULL
), dom AS (
  SELECT up.tag_id, up.at AS domain_id FROM up JOIN tags d ON d.id = up.at AND d.kind = 'domain'
), org_dom AS (
  SELECT DISTINCT x.org_id, dom.domain_id FROM (
    SELECT org_id, tag_id FROM org_tags
    UNION SELECT p.org_id, pt.tag_id FROM program_tags pt JOIN programs p ON p.id = pt.program_id
  ) x JOIN dom USING (tag_id)
), today AS (SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date AS d)
"""


async def flag_matches(pool: AsyncConnectionPool) -> dict:
    """Each org with members x each open call sharing a domain. DO NOTHING, so a re-run never touches status."""
    async with pool.connection() as conn:
        added = await (await conn.execute(DOMAINS + """
            INSERT INTO rfp_matches (rfp_id, org_id, matched_by, week_of)
            SELECT DISTINCT c.rfp_id, o.org_id, 'rules:domain', date_trunc('week', (SELECT d FROM today))::date
            FROM (SELECT DISTINCT rt.rfp_id, dom.domain_id FROM rfp_tags rt
                  JOIN dom USING (tag_id) JOIN rfps r ON r.id = rt.rfp_id
                  WHERE r.status = 'open' AND r.deadline >= (SELECT d FROM today)) c
            JOIN org_dom o USING (domain_id)
            WHERE EXISTS (SELECT 1 FROM org_members m WHERE m.org_id = o.org_id)
            ON CONFLICT DO NOTHING
            RETURNING org_id""")).fetchall()
        blind = await (await conn.execute(DOMAINS + """
            SELECT count(DISTINCT m.org_id) AS n FROM org_members m
            WHERE NOT EXISTS (SELECT 1 FROM org_dom o WHERE o.org_id = m.org_id)""")).fetchone()
    return {"added": len(added), "orgs": len({r["org_id"] for r in added}), "orgs_without_theme": blind["n"]}


async def feed(pool: AsyncConnectionPool, org_slug: str | None) -> dict | None:
    """One org's calls, as the caller: open ones not dismissed, and saved ones whatever became of the call.
    Without a slug, the caller's first organisation by name."""
    async with pool.connection() as conn:
        org = await (await conn.execute(DOMAINS + """
            SELECT o.id, o.slug, o.name,
                   (o.id IN (SELECT app.my_writable_org_ids())) OR (SELECT app.is_staff()) AS can_act,
                   ARRAY(SELECT d.label FROM org_dom od JOIN tags d ON d.id = od.domain_id
                         WHERE od.org_id = o.id ORDER BY d.label) AS domains,
                   (SELECT max(fetched_at) FROM rfps WHERE extractor_version LIKE 'calls-%%') AS last_pulled
            FROM orgs o WHERE o.slug = %(v)s OR (%(v)s::text IS NULL AND o.id = """ + FIRST_ORG + ")",
            {"v": org_slug})).fetchone()
        if org is None:
            return None
        rows = await (await conn.execute(DOMAINS + """
            SELECT r.id AS rfp_id, r.title, r.url, r.source_url, r.deadline, r.amount_min, r.amount_max,
                   r.status AS call_status, m.status, r.funder_id, f.name AS funder_name,
                   ARRAY(SELECT l.name FROM rfp_locations rl JOIN locations l ON l.id = rl.location_id
                         WHERE rl.rfp_id = r.id ORDER BY l.name) AS places,
                   (SELECT jsonb_agg(jsonb_build_array(d.label, NULLIF(t.label, d.label)))
                    FROM rfp_tags rt JOIN dom ON dom.tag_id = rt.tag_id
                    JOIN tags t ON t.id = rt.tag_id JOIN tags d ON d.id = dom.domain_id
                    WHERE rt.rfp_id = r.id
                      AND dom.domain_id IN (SELECT domain_id FROM org_dom WHERE org_id = m.org_id)) AS shared
            FROM rfp_matches m JOIN rfps r ON r.id = m.rfp_id LEFT JOIN funders f ON f.id = r.funder_id
            WHERE m.org_id = %s
              AND (m.status = 'saved'
                   OR (m.status <> 'dismissed' AND r.status = 'open' AND r.deadline >= (SELECT d FROM today)))
            ORDER BY r.deadline NULLS LAST, r.id""", (org["id"],))).fetchall()
    for r in rows:
        r["themes"] = _themes(r.pop("shared") or [])
    return {**org, "items": rows}


def _themes(pairs: list[list]) -> list[str]:
    """'Livelihoods · Skilling for jobs'; a bare domain only when no theme under it is tagged."""
    by_domain: dict[str, list[str]] = defaultdict(list)
    for domain, theme in pairs:
        if theme and theme not in by_domain[domain]:
            by_domain[domain].append(theme)
        by_domain.setdefault(domain, [])
    return [f"{d} · {t}" for d, ts in by_domain.items() for t in ts] + [d for d, ts in by_domain.items() if not ts]
