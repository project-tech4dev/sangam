"""What the catalog already holds, what it expects, and the step that writes to it.

Read-only but for `promote_research`, which is the one tool here that changes a
catalog row — and even that writes nothing of its own: it moves a saved
`entity_research` finding through `app/ingest/promote.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.agent.tools.sql.catalog import CATALOG
from app.db.pool import get_pool
from app.ingest.expectations import (
    CONCEPT_TABLES,
    concepts_for,
    expected_fields,
    recent_fiscal_years,
)
from app.ingest.promote import promote

logger = logging.getLogger(__name__)


@tool
async def funder_dossier(name: str) -> str:
    """Everything the catalog already holds about a funder. Read this BEFORE researching.

    Research fills gaps; it does not rediscover what is already recorded. This
    also gives you the baseline for the comparison you report at the end: what
    matches, what is new, what conflicts.

    A missing section means NOT RECORDED. It never means zero spending, no
    partners, no impact or no geography — say "not recorded", never "none".
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id, name, slug, funder_type, website, registry_status, parent_id, "
                    "section_135_bound FROM funders "
                    "WHERE name ILIKE %s OR similarity(name, %s) >= 0.4 "
                    "ORDER BY similarity(name, %s) DESC LIMIT 5",
                    (f"%{name}%", name, name),
                )
            ).fetchall()
            if not rows:
                return (
                    f"No funder in the catalog matches {name!r}. Everything you find is a NEW "
                    f"RECORD. That is not evidence the funder is absent from the sector."
                )
            top = rows[0]
            fid = top["id"]
            out = [
                f"funders [funder:{fid}] {top['name']} ({top['slug']})",
                (
                    f"  type={top['funder_type'] or 'not recorded'} "
                    f"website={top['website'] or 'not recorded'} "
                    f"section_135_bound={top['section_135_bound']} "
                    f"registry_status={top['registry_status']} parent_id={top['parent_id']}"
                ),
            ]
            if len(rows) > 1:
                others = ", ".join(f"{r['name']} [funder:{r['id']}]" for r in rows[1:])
                out.append(f"  other funders with a similar name: {others}")

            for label, sql in _DOSSIER_SECTIONS:
                found = await (await conn.execute(sql, (fid,))).fetchall()
                if not found:
                    out.append(f"\n{label}: NOT RECORDED")
                    continue
                out.append(f"\n{label} ({len(found)}):")
                out += [f"  {_row(r)}" for r in found[:20]]
                if len(found) > 20:
                    out.append(f"  … and {len(found) - 20} more")
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"funder_dossier failed: {exc}"


def _row(r: Any) -> str:
    return " ".join(f"{k}={v}" for k, v in r.items() if v is not None and k != "id")


# Read-only, fixed SQL, one query per concept the research brief targets.
# contacts deliberately omits email and phone: the catalog withholds them.
_DOSSIER_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "funder_identifiers",
        """
        SELECT id_type, id_value, verified FROM funder_identifiers
        WHERE funder_id = %s ORDER BY id_type
        """,
    ),
    (
        "funder_csr_years (amounts in INR)",
        """
        SELECT fiscal_year, prescribed_csr, total_spent, average_net_profit, unspent_transferred,
               source_name
        FROM funder_csr_years WHERE funder_id = %s ORDER BY fiscal_year
        """,
    ),
    (
        "funder_csr_spend",
        """
        SELECT fiscal_year, project_name, amount, implementing_agency, designation
        FROM funder_csr_spend WHERE funder_id = %s ORDER BY fiscal_year
        """,
    ),
    (
        "funder_footprints",
        """
        SELECT f.fiscal_year, f.name_as_printed, l.name AS location
        FROM funder_footprints f LEFT JOIN locations l ON l.id = f.location_id
        WHERE f.funder_id = %s ORDER BY f.fiscal_year
        """,
    ),
    (
        "funder_locations (STATED, not proof of spending)",
        """
        SELECT fl.role, l.name AS location FROM funder_locations fl
        JOIN locations l ON l.id = fl.location_id WHERE fl.funder_id = %s
        """,
    ),
    (
        "funder_partners",
        """
        SELECT fiscal_year, partner_name, partner_canonical, partner_kind
        FROM funder_partners WHERE funder_id = %s ORDER BY fiscal_year
        """,
    ),
    (
        "programs",
        """
        SELECT name, kind, status, start_date, end_date FROM programs
        WHERE funder_id = %s ORDER BY kind, name
        """,
    ),
    (
        "grants",
        """
        SELECT g.title, g.amount, g.status, g.start_date, o.name AS recipient
        FROM grants g JOIN orgs o ON o.id = g.org_id WHERE g.funder_id = %s
        """,
    ),
    (
        "metrics",
        """
        SELECT name, value, unit, period, stage, method FROM metrics
        WHERE funder_id = %s ORDER BY period
        """,
    ),
    (
        "contacts",
        """
        SELECT name, role, kind, verified FROM contacts WHERE funder_id = %s
        """,
    ),
    (
        "documents",
        """
        SELECT title, doc_type, as_of, source_url FROM documents
        WHERE funder_id = %s ORDER BY as_of
        """,
    ),
)


@tool
async def research_goals(name: str, years: str = "", entity_kind: str = "funder") -> str:
    """What to look for, derived from what the database expects. Call this FIRST.

    The catalog has a column for every fact worth finding, and this reads that
    list rather than repeating it: per concept, the fields a source could state,
    which of them the row cannot be written without, and what is already held
    for this funder. Research the gaps.

    Args:
        name: the organisation, as the user asked for it.
        years: comma-separated fiscal years, e.g. 'FY2024-25,FY2023-24'.
               Empty means the three most recent reportable years.
        entity_kind: 'funder' for a company or foundation, 'org' for an NGO.
               An NGO's facts hang off tables that have no writer, so the list
               is shorter and says so.
    """
    try:
        wanted = [y.strip() for y in years.split(",") if y.strip()] or list(recent_fiscal_years())
        pool = get_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT id, name FROM funders WHERE name ILIKE %s OR similarity(name, %s) >= 0.4 "
                    "ORDER BY similarity(name, %s) DESC LIMIT 1",
                    (f"%{name}%", name, name),
                )
            ).fetchone()
            held = await _held_per_concept(conn, row["id"]) if row else {}

        out = [
            (f"Research goals for {name!r}. These are the database's columns, not a wish list — "
             f"a field marked REQUIRED is one the row cannot be written without."),
            (f"\nYears to cover: {', '.join(wanted)}. Recurrence is the signal, so ask each year "
             f"separately and never mix them in one record."),
        ]
        out.append(
            f"\nIn the catalog as [funder:{row['id']}] {row['name']}."
            if row
            else f"\nNothing in the catalog matches {name!r}. Everything you find is a NEW RECORD. "
            f"That is not evidence the funder is absent from the sector."
        )

        wanted_concepts = concepts_for(entity_kind)
        if entity_kind == "org":
            out.append(
                "\nThis is an NGO. Everything below hangs off funders in the schema, and orgs "
                "has no writer yet — so research it fully, but expect it to stay research "
                "rather than become catalog rows. Saying that plainly is part of the job."
            )
        for concept in wanted_concepts:
            table = CONCEPT_TABLES[concept]
            fields = expected_fields(concept)
            count, seen_years = held.get(concept, (0, []))
            state = f"{count} row(s) held" if count else "NOT RECORDED"
            if seen_years:
                missing = [y for y in wanted if y not in seen_years]
                state += f", years {', '.join(sorted(seen_years))}"
                state += f" — still missing {', '.join(missing)}" if missing else " — years covered"
            out.append(f"\n{concept} -> {table}: {state}")
            out += [f"    {f.describe()}" for f in fields]

        out.append(
            "\nFields nothing can fill are as useful as fields you fill: say which you looked "
            "for and did not find, and pass them to save_research as not_found."
        )
        return "\n".join(out)
    except Exception as exc:
        logger.exception("research_goals failed")
        return f"research_goals failed: {type(exc).__name__}: {exc}"


async def _held_per_concept(conn: Any, funder_id: int) -> dict[str, tuple[int, list[str]]]:
    """Row counts, and the fiscal years already covered, per concept."""
    out: dict[str, tuple[int, list[str]]] = {}
    for concept, table in CONCEPT_TABLES.items():
        if concept == "identity":
            out[concept] = (1, [])
            continue
        # Table names come from CONCEPT_TABLES, a module constant, never a caller.
        has_year = any(c.name == "fiscal_year" for c in CATALOG[table].columns)
        years = ", array_agg(DISTINCT fiscal_year)" if has_year else ", '{}'::text[]"
        found = await (
            await conn.execute(
                f"SELECT count(*) AS n{years} AS years FROM {table} WHERE funder_id = %s",
                (funder_id,),
            )
        ).fetchone()
        out[concept] = (found["n"], [y for y in (found["years"] or []) if y])
    return out


@tool
async def promote_research(slug: str = "") -> str:
    """Move saved research into the catalog, where a writer exists for it.

    Research and the catalog are different: a finding is what a source said,
    a catalog row is what the product answers from. This is the step between.

    Only identity, identifier and csr_year findings can move — those are the
    concepts with writers. Everything else stays research and is reported as
    such, never silently dropped. A name that resembles an existing funder
    without matching it is NOT merged; it is reported for a person.

    Args:
        slug: one entity, or empty for every researched entity not yet promoted.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT DISTINCT ON (slug) * FROM entity_research "
                    + ("WHERE slug = %s " if slug else "")
                    + "ORDER BY slug, researched_at DESC",
                    (slug,) if slug else (),
                )
            ).fetchall()
        if not rows:
            return f"No saved research{f' for {slug!r}' if slug else ''}. Research first."

        reports = []
        async with pool.connection() as conn:
            for row in rows:
                async with conn.transaction():
                    reports.append(await promote(conn, dict(row)))

        lines = [f"Promoted {len(reports)} researched organisation(s) into the catalog."]
        for r in reports:
            if r["funder"]:
                years = ", ".join(f"{y['fiscal_year']} {y['status']}" for y in r["csr_years"])
                lines.append(
                    f"  {r['funder']['name']}: funder {r['funder']['status']} "
                    f"[funder:{r['funder']['id']}]" + (f" · CSR years {years}" if years else "")
                )
            for table, counts in sorted(r.get("written", {}).items()):
                tally = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
                lines.append(f"    {table}: {tally}")
            for reason in r["reasons"]:
                lines.append(f"  {r['slug']}: not promoted — {reason}")
            for held in r.get("held", []):
                lines.append(f"    held back: {held}")
            if r["skipped"]:
                skipped = ", ".join(f"{n} {c}" for c, n in sorted(r["skipped"].items()))
                lines.append(f"    still research only (no writer): {skipped}")
        lines.append(
            "\nA grant needs a recipient in orgs, which has no writer yet, so grant findings "
            "stay research — they are on file and in docs/entities/. Anything held back is "
            "named above: it is a decision waiting for a person, not a silent loss."
        )
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("promote_research failed")
        return f"promote_research failed: {type(exc).__name__}: {exc}"
