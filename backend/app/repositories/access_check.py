from __future__ import annotations

from psycopg import sql
from psycopg.errors import InsufficientPrivilege
from psycopg_pool import AsyncConnectionPool


# No WHERE on purpose: RLS is the only filter, so what comes back is what the caller's role may see.
# LEFT JOIN: a user or org the caller may not read still keeps its row, named as hidden.
ACCESS_CHECK_TABLES = {
    "users": """
        SELECT coalesce(display_name, '—') AS name, email, CASE WHEN is_staff THEN 'yes' ELSE 'no' END AS staff
        FROM users ORDER BY email
    """,
    "org_members": """
        SELECT coalesce(o.name, 'hidden org #' || m.org_id) AS org,
               coalesce(u.display_name, u.email, 'hidden user') AS member,
               u.email, m.role
        FROM org_members m
        LEFT JOIN orgs o ON o.id = m.org_id
        LEFT JOIN users u ON u.id = m.user_id
        ORDER BY org, m.role, member
    """,
    "threads": """
        SELECT coalesce(u.display_name, u.email, 'hidden user') AS owner,
               coalesce(o.name, '—') AS org, t.visibility,
               to_char(t.created_at, 'DD Mon YYYY HH24:MI') AS created, t.thread_id
        FROM threads t
        LEFT JOIN users u ON u.id = t.user_id
        LEFT JOIN orgs o ON o.id = t.org_id
        ORDER BY t.created_at DESC
    """,
    "proposals": """
        SELECT coalesce(o.name, 'hidden org #' || p.org_id) AS org, p.title,
               coalesce(f.name, '—') AS funder, p.status,
               to_char(p.requested_amount, 'FM99,99,99,999') AS amount_inr, p.duration_months AS months
        FROM proposals p
        LEFT JOIN orgs o ON o.id = p.org_id
        LEFT JOIN funders f ON f.id = p.funder_id
        ORDER BY org, p.id
    """,
    "rfp_matches": """
        SELECT coalesce(o.name, 'hidden org #' || m.org_id) AS org, r.title AS rfp,
               m.match_score AS score, m.status, m.match_notes AS notes
        FROM rfp_matches m
        LEFT JOIN orgs o ON o.id = m.org_id
        LEFT JOIN rfps r ON r.id = m.rfp_id
        ORDER BY org, m.match_score DESC
    """,
}


async def access_identity(pool: AsyncConnectionPool) -> dict:
    sql = "SELECT current_user AS db_role, app.user_id() AS user_id, app.is_staff() AS is_staff"
    async with pool.connection() as conn:
        return await (await conn.execute(sql)).fetchone()


async def my_orgs(pool: AsyncConnectionPool) -> list[dict]:
    """The orgs the caller belongs to, read as the caller through org_members and orgs."""
    sql = """
    SELECT o.name AS org, m.role, o.registry_status AS status, o.id AS org_id
    FROM org_members m
    JOIN orgs o ON o.id = m.org_id
    WHERE m.user_id = app.user_id()
    ORDER BY o.name
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql)).fetchall()


async def access_rows(pool: AsyncConnectionPool, table: str) -> list[dict] | None:
    """The table's rows as the caller; None when the role was not granted it."""
    try:
        async with pool.connection() as conn:
            return await (await conn.execute(ACCESS_CHECK_TABLES[table])).fetchall()
    except InsufficientPrivilege:
        return None


# The public tables of 0027: USING (true), granted to anon and authenticated, so signed out sees every row.
PUBLIC_TABLES = {
    "Programs": ["programs", "program_locations", "program_tags"],
    "Grants": ["grants", "grant_locations"],
    "RFPs": ["rfps", "rfp_locations", "rfp_tags"],
    "Scoring": ["rubrics", "rubric_criteria", "fit_scores", "fit_score_items", "score_adjustments"],
    "Signals": ["credential_events", "news_mentions", "metrics", "reference_figures", "extraction_log"],
    "Reference": ["tags", "locations", "location_designations", "proposal_templates", "template_items"],
}


# The staff-only tables of 0027: granted to authenticated, RLS USING (app.is_staff()). Sangam Import.
STAFF_ONLY_TABLES = {
    "Sangam Import": [
        "ingest_runs", "ingest_run_items", "ingest_source_proposals", "entity_research", "resolution_queue",
    ],
}


async def sample_table(pool: AsyncConnectionPool, table: str, limit: int) -> dict:
    """How many rows of a listed table the caller sees, and the first few; allowed is False on a 403."""
    name = sql.Identifier(table)
    try:
        async with pool.connection() as conn:
            total = (await (await conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(name))).fetchone())["n"]
            rows = await (
                await conn.execute(sql.SQL("SELECT * FROM {} ORDER BY 1 LIMIT %s").format(name), (limit,))
            ).fetchall()
        return {"table": table, "allowed": True, "count": total, "rows": rows}
    except InsufficientPrivilege:
        return {"table": table, "allowed": False, "count": 0, "rows": []}


# The public-by-flag tables of 0027: is_public rows to everyone, private rows to that org's people and staff.
# A private funder row has no org, so only staff see it.
FLAG_TABLES = {
    "contacts": """
        SELECT coalesce(o.name, f.name) AS owner, c.name, c.role, c.email, c.is_public AS public, {why} AS why
        FROM contacts c LEFT JOIN orgs o ON o.id = c.org_id LEFT JOIN funders f ON f.id = c.funder_id
    """,
    "documents": """
        SELECT coalesce(o.name, f.name) AS owner, c.title, c.doc_type, c.is_public AS public, {why} AS why
        FROM documents c LEFT JOIN orgs o ON o.id = c.org_id LEFT JOIN funders f ON f.id = c.funder_id
    """,
    "org_identifiers": """
        SELECT o.name AS owner, c.id_type, c.id_value, c.is_public AS public, {why} AS why
        FROM org_identifiers c LEFT JOIN orgs o ON o.id = c.org_id
    """,
}

_KIND = """CASE WHEN c.is_public THEN 'public'
                WHEN c.org_id = ANY(%(mine)s) THEN 'my org, private'
                WHEN c.org_id IS NOT NULL THEN 'other org, private'
                ELSE 'funder, private' END"""

FLAG_KINDS = ["public", "my org, private", "other org, private", "funder, private"]


async def my_org_ids(pool: AsyncConnectionPool) -> list[int]:
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT id FROM app.my_org_ids() id")).fetchall()
    return [r["id"] for r in rows]


async def flag_counts(pool: AsyncConnectionPool, table: str, mine: list[int]) -> dict[str, int]:
    """Rows of a public-by-flag table by kind, read through whichever pool is passed."""
    query = sql.SQL("SELECT {kind} AS kind, count(*) AS n FROM {table} c GROUP BY 1").format(
        kind=sql.SQL(_KIND), table=sql.Identifier(table)
    )
    async with pool.connection() as conn:
        rows = await (await conn.execute(query, {"mine": mine})).fetchall()
    return {r["kind"]: r["n"] for r in rows}


async def flag_rows(pool: AsyncConnectionPool, table: str, mine: list[int], limit: int) -> list[dict]:
    """The rows the caller sees, private first, each saying why it is visible."""
    query = FLAG_TABLES[table].format(why=_KIND) + " ORDER BY c.is_public, owner LIMIT %(limit)s"
    async with pool.connection() as conn:
        return await (await conn.execute(query, {"mine": mine, "limit": limit})).fetchall()
