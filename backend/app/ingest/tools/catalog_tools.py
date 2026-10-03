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
async def funder_dossier(name: str, entity_kind: str = "funder") -> str:
    """Everything the catalog already holds about a funder or an NGO. Read this BEFORE researching.

    Research fills gaps; it does not rediscover what is already recorded. This
    also gives you the baseline for the comparison you report at the end: what
    matches, what is new, what conflicts.

    A missing section means NOT RECORDED. It never means zero spending, no
    partners, no impact or no geography — say "not recorded", never "none".

    Args:
        name: the organisation, as the user asked for it.
        entity_kind: 'funder' (the default) reads the funder tables; 'org'
               reads an NGO's. A parameter rather than a second tool, so there
               is one dossier to name in one prompt.
    """
    refusal = _reject_unknown(entity_kind)
    if refusal:
        return refusal
    entity_table, _, sections = _BY_KIND[entity_kind]
    noun = "funder" if entity_kind == "funder" else "organisation"
    # Both tables carry these; funder_type and section_135_bound are a funder's
    # and org_kind and legal_form are an NGO's, so the head line differs.
    head = (
        "id, name, slug, registry_status, funder_type, website, parent_id, section_135_bound"
        if entity_kind == "funder"
        else "id, name, slug, registry_status, org_kind, legal_form, registration_date, cohort"
    )
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            # Column and table names come from the branch above, never a caller.
            rows = await (
                await conn.execute(
                    f"SELECT {head} FROM {entity_table} "
                    "WHERE name ILIKE %s OR similarity(name, %s) >= 0.4 "
                    "ORDER BY similarity(name, %s) DESC LIMIT 5",
                    (f"%{name}%", name, name),
                )
            ).fetchall()
            if not rows:
                return (
                    f"No {noun} in the catalog matches {name!r}. Everything you find is a NEW "
                    f"RECORD. That is not evidence the {noun} is absent from the sector."
                )
            top = rows[0]
            fid = top["id"]
            out = [
                f"{entity_table} [{entity_kind}:{fid}] {top['name']} ({top['slug']})",
                "  " + " ".join(
                    f"{k}={top[k] if top[k] is not None else 'not recorded'}"
                    for k in top
                    if k not in ("id", "name", "slug")
                ),
            ]
            if len(rows) > 1:
                others = ", ".join(f"{r['name']} [{entity_kind}:{r['id']}]" for r in rows[1:])
                out.append(f"  other rows with a similar name: {others}")

            for label, sql in sections:
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

# The org side. Not a rewrite of the tuple above with a different column: an
# NGO's facts live in different tables, and the four shared ones (programs,
# metrics, contacts, documents) are the same query with the other foreign key.
_ORG_DOSSIER_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "org_identifiers (12A, 80G and FCRA live here)",
        """
        SELECT id_type, id_value, verified, is_current FROM org_identifiers
        WHERE org_id = %s ORDER BY id_type
        """,
    ),
    (
        "org_financials (amounts in INR)",
        """
        SELECT fiscal_year, total_income, program_spend, non_program_spend,
               foreign_contribution, is_audited
        FROM org_financials WHERE org_id = %s ORDER BY fiscal_year
        """,
    ),
    (
        "org_locations",
        """
        SELECT ol.role, l.name AS location FROM org_locations ol
        JOIN locations l ON l.id = ol.location_id WHERE ol.org_id = %s
        """,
    ),
    (
        "programs",
        """
        SELECT name, kind, status, start_date, end_date FROM programs
        WHERE org_id = %s ORDER BY kind, name
        """,
    ),
    (
        "grants received",
        """
        SELECT g.title, g.amount, g.status, g.start_date, f.name AS funder
        FROM grants g JOIN funders f ON f.id = g.funder_id WHERE g.org_id = %s
        """,
    ),
    (
        "metrics",
        """
        SELECT name, value, unit, period, stage, method FROM metrics
        WHERE org_id = %s ORDER BY period
        """,
    ),
    (
        "contacts",
        """
        SELECT name, role, kind, verified FROM contacts WHERE org_id = %s
        """,
    ),
    (
        "documents",
        """
        SELECT title, doc_type, as_of, source_url FROM documents
        WHERE org_id = %s ORDER BY as_of
        """,
    ),
)

# Everything that differs between a funder run and an org run, in one place, so
# that adding a kind is adding a row rather than editing four `if`s.
_BY_KIND: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    # kind -> (entity table, foreign key, dossier sections)
    "funder": ("funders", "funder_id", _DOSSIER_SECTIONS),
    "org": ("orgs", "org_id", _ORG_DOSSIER_SECTIONS),
}


def _reject_unknown(entity_kind: str) -> str | None:
    """`unknown` is a save-time value, never a research target.

    It is what a not_found or wrong_entity row is saved as, and legacy rows
    hold it, so the column keeps it. But a run that has not decided which kind
    it is researching cannot be given a target list: it would get a funder's,
    which is how an NGO ended up aimed at funder_identifiers.
    """
    if entity_kind in _BY_KIND:
        return None
    return (
        f"REFUSED: entity_kind must be 'funder' or 'org', not {entity_kind!r}. Decide first: "
        f"one search answers it. A company, corporate foundation or trust that GIVES money is "
        f"'funder' — BSE/NSE, MCA, csr.gov.in, a CSR annexure. An organisation that RECEIVES "
        f"it is 'org' — NGO-Darpan, GuideStar India, a 12A/80G page. Say which and why, then "
        f"call this again."
    )


@tool
async def research_goals(name: str, entity_kind: str, years: str = "") -> str:
    """What to look for, derived from what the database expects. Call this FIRST.

    The catalog has a column for every fact worth finding, and this reads that
    list rather than repeating it: per concept, the fields a source could state,
    which of them the row cannot be written without, and what is already held
    for this entity. Research the gaps.

    Args:
        name: the organisation, as the user asked for it.
        entity_kind: 'funder' for a company, corporate foundation or trust that
               GIVES money; 'org' for an NGO that RECEIVES it. Required, and
               'unknown' is refused: the two get different tables, and an NGO
               aimed at a funder's has nowhere to put its 12A, 80G or FCRA.
        years: comma-separated fiscal years, e.g. 'FY2024-25,FY2023-24'.
               Empty means the three most recent reportable years.
    """
    refusal = _reject_unknown(entity_kind)
    if refusal:
        return refusal
    entity_table, _, _ = _BY_KIND[entity_kind]
    try:
        wanted = [y.strip() for y in years.split(",") if y.strip()] or list(recent_fiscal_years())
        pool = get_pool()
        async with pool.connection() as conn:
            # entity_table comes from _BY_KIND, a module constant, never a caller.
            row = await (
                await conn.execute(
                    f"SELECT id, name FROM {entity_table} "
                    "WHERE name ILIKE %s OR similarity(name, %s) >= 0.4 "
                    "ORDER BY similarity(name, %s) DESC LIMIT 1",
                    (f"%{name}%", name, name),
                )
            ).fetchone()
            held = await _held_per_concept(conn, row["id"], entity_kind) if row else {}

        out = [
            (f"Research goals for {name!r}. These are the database's columns, not a wish list — "
             f"a field marked REQUIRED is one the row cannot be written without."),
            (f"\nYears to cover: {', '.join(wanted)}. Recurrence is the signal, so ask each year "
             f"separately and never mix them in one record."),
        ]
        noun = "funder" if entity_kind == "funder" else "organisation"
        out.append(
            f"\nIn the catalog as [{entity_kind}:{row['id']}] {row['name']}."
            if row
            else f"\nNothing in the catalog matches {name!r}. Everything you find is a NEW RECORD. "
            f"That is not evidence the {noun} is absent from the sector."
        )

        wanted_concepts = concepts_for(entity_kind)
        if entity_kind == "org":
            out.append(
                "\nThis is an NGO, so these are the org tables: its registrations are 12A, 80G "
                "and FCRA, not a CSR-1, and its money is income and programme spend rather than "
                "a Section 135 obligation. orgs has no writer yet — research it fully, it is "
                "saved and it renders, but expect it to stay research rather than become "
                "catalog rows. Saying that plainly is part of the job."
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


async def _held_per_concept(
    conn: Any, entity_id: int, entity_kind: str
) -> dict[str, tuple[int, list[str]]]:
    """Row counts, and the fiscal years already covered, per concept.

    Both halves have to move together. This used to walk every concept in the
    registry and emit `WHERE funder_id = %s`, which was fine while every table
    had one — the moment orgs tables joined the registry it became `SELECT …
    FROM orgs WHERE funder_id = %s`, an UndefinedColumn swallowed by the broad
    `except` in research_goals, **for funder runs too**, because the loop runs
    before anything is printed. So it iterates the concepts for this kind and
    takes the foreign key from the same place.
    """
    entity_table, fk, _ = _BY_KIND[entity_kind]
    out: dict[str, tuple[int, list[str]]] = {}
    for concept in concepts_for(entity_kind):
        table = CONCEPT_TABLES[concept]
        # The entity's own row, which is the match we already have in hand.
        if table == entity_table:
            out[concept] = (1, [])
            continue
        # Table and column names come from module constants, never a caller.
        has_year = any(c.name == "fiscal_year" for c in CATALOG[table].columns)
        years = ", array_agg(DISTINCT fiscal_year)" if has_year else ", '{}'::text[]"
        found = await (
            await conn.execute(
                f"SELECT count(*) AS n{years} AS years FROM {table} WHERE {fk} = %s",
                (entity_id,),
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
