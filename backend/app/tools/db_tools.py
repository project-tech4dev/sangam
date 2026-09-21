"""Agent tools over the sangam Postgres database.

Discipline (from deep-agent-app): tools NEVER raise — a raised exception aborts
the whole agent run, while an error string lets the model see and adapt. Every
row is rendered with a citation marker ([org:N] / [funder:N] / [score:N]) that
the system prompt requires the model to repeat inline.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.db import get_pool


def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else "date unknown"


@tool
async def search_orgs(query: str) -> str:
    """Search CSOs/NGOs by name, sector, state, or district.

    Returns matching organisations with [org:ID] citation markers, registration
    status, and data provenance. Use an empty query to list all organisations.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT id, name, slug, darpan_id, state, district, sectors,
                           registration, source_name, source_url, fetched_at
                    FROM orgs
                    WHERE %(q)s = ''
                       OR name ILIKE '%%' || %(q)s || '%%'
                       OR slug ILIKE '%%' || %(q)s || '%%'
                       OR state ILIKE '%%' || %(q)s || '%%'
                       OR district ILIKE '%%' || %(q)s || '%%'
                       OR EXISTS (SELECT 1 FROM unnest(sectors) s WHERE s ILIKE '%%' || %(q)s || '%%')
                       OR similarity(name, %(q)s) > 0.3
                    ORDER BY similarity(name, %(q)s) DESC NULLS LAST, name
                    LIMIT 15
                    """,
                    {"q": query.strip()},
                )
            ).fetchall()
        if not rows:
            return f"No organisations found matching {query!r}."
        lines = []
        for r in rows:
            reg = r["registration"] or {}
            reg_bits = ", ".join(
                f"{k.upper()}: {v}" for k, v in reg.items()
                if k in ("pan", "12a", "80g", "fcra", "csr1") and v
            )
            lines.append(
                f"[org:{r['id']}] {r['name']} ({r['slug']})"
                + (f" — Darpan {r['darpan_id']}" if r["darpan_id"] else "")
                + f" — {r['district'] or '?'}, {r['state'] or '?'}"
                + (f" — sectors: {', '.join(r['sectors'])}" if r["sectors"] else "")
                + (f" — {reg_bits}" if reg_bits else "")
                + f" — source: {r['source_name'] or 'unknown'}, fetched {_fmt_date(r['fetched_at'])}"
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"search_orgs failed: {exc}"


@tool
async def get_funder(name: str) -> str:
    """Look up a funder's profile by name or slug.

    Returns the funder's type, focus sectors, geographies, funding trend and
    other profile facts with a [funder:ID] citation marker, plus any contacts.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT id, name, slug, funder_type, website, focus_sectors,
                           geographies, profile, source_name, source_url, fetched_at
                    FROM funders
                    WHERE name ILIKE '%%' || %(q)s || '%%'
                       OR slug ILIKE '%%' || %(q)s || '%%'
                       OR similarity(name, %(q)s) > 0.3
                    ORDER BY similarity(name, %(q)s) DESC NULLS LAST
                    LIMIT 5
                    """,
                    {"q": name.strip()},
                )
            ).fetchall()
            if not rows:
                return f"No funder found matching {name!r}."
            out = []
            for r in rows:
                profile = r["profile"] or {}
                profile_bits = "\n".join(f"  - {k}: {v}" for k, v in profile.items())
                contacts = await (
                    await conn.execute(
                        "SELECT name, role, email, verified FROM funder_contacts WHERE funder_id = %s",
                        (r["id"],),
                    )
                ).fetchall()
                contact_bits = "\n".join(
                    f"  - {c['name']} ({c['role']}){' [verified]' if c['verified'] else ''}"
                    for c in contacts
                )
                out.append(
                    f"[funder:{r['id']}] {r['name']} ({r['slug']}) — {r['funder_type']}\n"
                    f"  website: {r['website']}\n"
                    f"  focus: {', '.join(r['focus_sectors'])}\n"
                    f"  geographies: {', '.join(r['geographies'])}\n"
                    + (profile_bits + "\n" if profile_bits else "")
                    + (f"  contacts:\n{contact_bits}\n" if contact_bits else "")
                    + f"  source: {r['source_name'] or 'unknown'}"
                )
            return "\n\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"get_funder failed: {exc}"


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
            scores = await (
                await conn.execute(
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
                )
            ).fetchall()
            if not scores:
                return f"No fit scores found for org {org!r}" + (f" and funder {funder!r}" if funder else "") + "."
            out = []
            for s in scores:
                items = await (
                    await conn.execute(
                        """
                        SELECT rc.code, rc.label, rc.points, fsi.score, fsi.justification
                        FROM fit_score_items fsi
                        JOIN rubric_criteria rc ON rc.id = fsi.criterion_id
                        WHERE fsi.fit_score_id = %s
                        ORDER BY rc.code
                        """,
                        (s["id"],),
                    )
                ).fetchall()
                adjustments = await (
                    await conn.execute(
                        """
                        SELECT rc.code, sa.old_score, sa.new_score, sa.reason, sa.adjusted_at
                        FROM score_adjustments sa
                        JOIN rubric_criteria rc ON rc.id = sa.criterion_id
                        WHERE sa.fit_score_id = %s
                        ORDER BY rc.code
                        """,
                        (s["id"],),
                    )
                ).fetchall()
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
