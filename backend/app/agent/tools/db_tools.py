"""Agent tools over the sangam Postgres database (schema v2).

Discipline (from deep-agent-app): tools NEVER raise — a raised exception aborts
the whole agent run, while an error string lets the model see and adapt. Every
row is rendered with a citation marker ([org:N] / [funder:N] / [score:N] /
[grant:N]) that the system prompt requires the model to repeat inline.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.agent.tools.sql.catalog import DEFECTS
from app.db.pool import get_pool
from app.integrations.tracing import traced_fetch


def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else "date unknown"


def _caveats(*tables: str) -> str:
    """Known data problems for the tables a curated query read.

    The catalog is the single source of truth for these, but it was reachable
    only from the SQL tools — so the same broken rows came back uncaveated
    through the curated path, and the model fell back on its own world
    knowledge to spot them. It catches most and misses some, which is worse
    than either extreme because the misses look like confirmations.
    """
    lines = [d for table in tables for d in DEFECTS.get(table, ())]
    return ("\n\nCAVEAT: " + " ".join(lines)) if lines else ""


@tool
async def search_orgs(query: str) -> str:
    """Search CSOs/NGOs by name, sector, state, district, or registration ID
    (PAN/FCRA/Darpan etc.).

    Returns matching organisations with [org:ID] citation markers, compliance
    identifiers, and data provenance. Use an empty query to list all organisations.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await traced_fetch(
                conn,
                """
                SELECT o.id, o.name, o.slug, o.legal_form, o.registration_date,
                       o.source_name, o.source_url, o.fetched_at,
                       dl.name AS district, sl.name AS state,
                       COALESCE(t.sectors, '{}') AS sectors,
                       COALESCE(i.ids, '') AS ids
                FROM orgs o
                LEFT JOIN locations dl ON dl.id = o.registered_location_id
                LEFT JOIN locations sl ON sl.id = dl.parent_id
                LEFT JOIN LATERAL (
                  SELECT array_agg(tg.label ORDER BY ot.role, tg.label) AS sectors
                  FROM org_tags ot JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = o.id
                ) t ON true
                LEFT JOIN LATERAL (
                  SELECT string_agg(upper(oi.id_type) || ': ' || oi.id_value, ', '
                                    ORDER BY oi.id_type) AS ids
                  FROM org_identifiers oi WHERE oi.org_id = o.id
                ) i ON true
                WHERE %(q)s = ''
                   OR o.name ILIKE '%%' || %(q)s || '%%'
                   OR o.slug ILIKE '%%' || %(q)s || '%%'
                   OR sl.name ILIKE '%%' || %(q)s || '%%'
                   OR dl.name ILIKE '%%' || %(q)s || '%%'
                   OR similarity(o.name, %(q)s) > 0.3
                   OR EXISTS (SELECT 1 FROM org_tags ot2 JOIN tags tg2 ON tg2.id = ot2.tag_id
                              WHERE ot2.org_id = o.id AND tg2.label ILIKE '%%' || %(q)s || '%%')
                   OR EXISTS (SELECT 1 FROM org_identifiers oi2
                              WHERE oi2.org_id = o.id AND oi2.id_value ILIKE %(q)s)
                ORDER BY similarity(o.name, %(q)s) DESC NULLS LAST, o.name
                LIMIT 15
                """,
                {"q": query.strip()},
                name="query-orgs",
            )
        if not rows:
            return f"No organisations found matching {query!r}." + _caveats("locations")
        lines = []
        for r in rows:
            lines.append(
                f"[org:{r['id']}] {r['name']} ({r['slug']})"
                + (f" — {r['legal_form']}" if r["legal_form"] else "")
                + f" — {r['district'] or '?'}, {r['state'] or '?'}"
                + (f" — sectors: {', '.join(r['sectors'])}" if r["sectors"] else "")
                + (f" — {r['ids']}" if r["ids"] else "")
                + f" — source: {r['source_name'] or 'unknown'}, fetched {_fmt_date(r['fetched_at'])}"
            )
        return "\n".join(lines) + _caveats("locations")
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"search_orgs failed: {exc}"


@tool
async def get_funder(name: str) -> str:
    """Look up a funder's profile by name or slug.

    Returns funder type, Section-135 status, focus sectors, geographies, profile
    facts, contacts, and a summary of its known grants — with [funder:ID] and
    [grant:ID] citation markers.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await traced_fetch(
                conn,
                """
                SELECT f.id, f.name, f.slug, f.funder_type, f.section_135_bound,
                       f.website, f.profile, f.source_name, f.source_url, f.fetched_at,
                       COALESCE(t.sectors, '{}') AS focus_sectors,
                       COALESCE(l.geos, '{}') AS geographies
                FROM funders f
                LEFT JOIN LATERAL (
                  SELECT array_agg(tg.label ORDER BY ft.role, tg.label) AS sectors
                  FROM funder_tags ft JOIN tags tg ON tg.id = ft.tag_id WHERE ft.funder_id = f.id
                ) t ON true
                LEFT JOIN LATERAL (
                  SELECT array_agg(lo.name ORDER BY lo.kind, lo.name) AS geos
                  FROM funder_locations fl JOIN locations lo ON lo.id = fl.location_id
                  WHERE fl.funder_id = f.id
                ) l ON true
                WHERE f.name ILIKE '%%' || %(q)s || '%%'
                   OR f.slug ILIKE '%%' || %(q)s || '%%'
                   OR similarity(f.name, %(q)s) > 0.3
                ORDER BY similarity(f.name, %(q)s) DESC NULLS LAST
                LIMIT 5
                """,
                {"q": name.strip()},
                name="query-funders",
            )
            if not rows:
                return f"No funder found matching {name!r}."
            out = []
            for r in rows:
                profile = r["profile"] or {}
                profile_bits = "\n".join(f"  - {k}: {v}" for k, v in profile.items())
                contacts = await traced_fetch(
                    conn,
                    "SELECT name, role, kind, verified FROM contacts WHERE funder_id = %s",
                    (r["id"],),
                    name="fetch-funder-contacts",
                )
                contact_bits = "\n".join(
                    f"  - {c['name']} ({c['role'] or c['kind']}){' [verified]' if c['verified'] else ''}"
                    for c in contacts
                )
                grants = await traced_fetch(
                    conn,
                    """
                    SELECT g.id, o.name AS org_name, g.title, g.status,
                           g.start_date, g.end_date
                    FROM grants g JOIN orgs o ON o.id = g.org_id
                    WHERE g.funder_id = %s ORDER BY g.start_date DESC NULLS LAST
                    """,
                    (r["id"],),
                    name="fetch-funder-grants",
                )
                grant_bits = "\n".join(
                    f"  - [grant:{g['id']}] → {g['org_name']}: {g['title']} "
                    f"({g['status']}, {_fmt_date(g['start_date'])} – {_fmt_date(g['end_date'])})"
                    for g in grants
                )
                section = ("Section-135-bound CSR" if r["section_135_bound"]
                           else "not Section-135-bound" if r["section_135_bound"] is False
                           else "Section-135 status unknown")
                out.append(
                    f"[funder:{r['id']}] {r['name']} ({r['slug']}) — {r['funder_type']}, {section}\n"
                    f"  website: {r['website']}\n"
                    f"  focus: {', '.join(r['focus_sectors'])}\n"
                    f"  geographies: {', '.join(r['geographies'])}\n"
                    + (profile_bits + "\n" if profile_bits else "")
                    + (f"  contacts:\n{contact_bits}\n" if contact_bits else "")
                    + (f"  known grants:\n{grant_bits}\n" if grant_bits else "")
                    + f"  source: {r['source_name'] or 'unknown'}"
                )
            return "\n\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"get_funder failed: {exc}"


@tool
async def get_grants(org: str = "", funder: str = "", status: str = "") -> str:
    """Look up actual funding relationships (grants) between funders and orgs.

    Args:
        org: optional organisation name/slug filter.
        funder: optional funder name/slug filter.
        status: optional status filter — active | concluded | unconfirmed | dormant.

    Returns grants with [grant:ID] markers, dates, program, outcomes, and source.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await traced_fetch(
                conn,
                """
                SELECT g.*, f.name AS funder_name, f.id AS f_id,
                       o.name AS org_name, o.id AS o_id, p.name AS program_name
                FROM grants g
                JOIN funders f ON f.id = g.funder_id
                JOIN orgs o ON o.id = g.org_id
                LEFT JOIN programs p ON p.id = g.program_id
                WHERE (%(org)s = '' OR o.name ILIKE '%%' || %(org)s || '%%' OR o.slug ILIKE '%%' || %(org)s || '%%')
                  AND (%(funder)s = '' OR f.name ILIKE '%%' || %(funder)s || '%%' OR f.slug ILIKE '%%' || %(funder)s || '%%')
                  AND (%(status)s = '' OR g.status = %(status)s)
                ORDER BY g.start_date DESC NULLS LAST
                LIMIT 20
                """,
                {"org": org.strip(), "funder": funder.strip(), "status": status.strip()},
                name="query-grants",
            )
        if not rows:
            return ("No grants found for the given filters. Note: only researched "
                    "relationships are recorded; absence here is not proof no grant exists.")
        lines = []
        for g in rows:
            outcomes = ", ".join(f"{k}: {v}" for k, v in (g["outcomes"] or {}).items())
            amount = f"₹{g['amount']:,.0f}" if g["amount"] is not None else "amount not public"
            lines.append(
                f"[grant:{g['id']}] {g['funder_name']} [funder:{g['f_id']}] → "
                f"{g['org_name']} [org:{g['o_id']}] — {g['title']} "
                f"({g['status']}, {_fmt_date(g['start_date'])} – {_fmt_date(g['end_date'])}, {amount})"
                + (f" — program: {g['program_name']}" if g["program_name"] else "")
                + (f" — outcomes: {outcomes}" if outcomes else "")
                + (f" — note: {g['notes']}" if g["notes"] else "")
                + f" — source: {g['source_name'] or 'unknown'}, as of {_fmt_date(g['fetched_at'])}"
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"get_grants failed: {exc}"


@tool
async def get_fit_scores(org: str, funder: str = "", rubric_version: str = "") -> str:
    """Get rubric-based funder-fit scores for an organisation.

    Args:
        org: organisation name or slug (e.g. "KABIL").
        funder: optional funder name/slug to filter to one funder.
        rubric_version: optional rubric version filter ("v1" or "v2"); empty = all.

    Returns each assessment with [score:ID] markers, the per-criterion breakdown
    with justifications, and any manual hand-vetting adjustments.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            scores = await traced_fetch(
                conn,
                """
                SELECT fs.id, fs.total_score, fs.max_score, fs.scored_by, fs.scored_at,
                       fs.notes, o.name AS org_name, o.id AS org_id,
                       f.name AS funder_name, f.id AS funder_id, r.version, r.name AS rubric_name
                FROM fit_scores fs
                JOIN orgs o ON o.id = fs.org_id
                JOIN funders f ON f.id = fs.funder_id
                JOIN rubrics r ON r.id = fs.rubric_id
                WHERE (o.name ILIKE '%%' || %(org)s || '%%' OR o.slug ILIKE '%%' || %(org)s || '%%')
                  AND (%(funder)s = '' OR f.name ILIKE '%%' || %(funder)s || '%%'
                       OR f.slug ILIKE '%%' || %(funder)s || '%%')
                  AND (%(rubric)s = '' OR r.version = %(rubric)s)
                ORDER BY r.version, fs.total_score DESC
                """,
                {"org": org.strip(), "funder": funder.strip(), "rubric": rubric_version.strip()},
                name="query-fit-scores",
            )
            if not scores:
                return f"No fit scores found for org {org!r}" + (f" and funder {funder!r}" if funder else "") + "."
            out = []
            for s in scores:
                items = await traced_fetch(
                    conn,
                    """
                    SELECT rc.code, rc.label, rc.points, fsi.score, fsi.justification
                    FROM fit_score_items fsi
                    JOIN rubric_criteria rc ON rc.id = fsi.criterion_id
                    WHERE fsi.fit_score_id = %s
                    ORDER BY rc.code
                    """,
                    (s["id"],),
                    name="fetch-score-criteria",
                )
                adjustments = await traced_fetch(
                    conn,
                    """
                    SELECT rc.code, sa.old_score, sa.new_score, sa.reason, sa.adjusted_at
                    FROM score_adjustments sa
                    JOIN rubric_criteria rc ON rc.id = sa.criterion_id
                    WHERE sa.fit_score_id = %s
                    ORDER BY rc.code
                    """,
                    (s["id"],),
                    name="fetch-score-adjustments",
                )
                block = [
                    f"[score:{s['id']}] {s['org_name']} × {s['funder_name']} — "
                    f"{s['total_score']}/{s['max_score']} on rubric {s['version']} "
                    f"({s['scored_by']}, scored {_fmt_date(s['scored_at'])})"
                    f" [org:{s['org_id']}] [funder:{s['funder_id']}]"
                ]
                if s["notes"]:
                    block.append(f"  notes: {s['notes']}")
                for i in items:
                    block.append(
                        f"  {i['code']}. {i['label']}: {i['score']}/{i['points']}"
                        + (f" — {i['justification']}" if i["justification"] else "")
                    )
                for a in adjustments:
                    block.append(
                        f"  ADJUSTED {a['code']}: {a['old_score']} → {a['new_score']} "
                        f"({_fmt_date(a['adjusted_at'])}) — {a['reason']}"
                    )
                out.append("\n".join(block))
            return "\n\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"get_fit_scores failed: {exc}"
