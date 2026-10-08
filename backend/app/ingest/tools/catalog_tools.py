"""What the catalog already holds, what it expects, and the two steps that write to it.

Read-only but for `promote_research`, which moves saved research through `promote.py`, and
`record_registry_check`, which records a staff member's own registry check through `manual_checks.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.agent.tools.sql.catalog import CATALOG
from app.core.security import chat_user_id
from app.db.pool import get_pool
from app.ingest import manual_checks
from app.ingest.expectations import (
    CONCEPTS,
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
        "id, name, slug, registry_status, funder_type, website, parent_id, section_135_bound, cin, aliases, "
        "intake_mode, funds_external, typical_duration_months, grant_size_min, grant_size_max"
        if entity_kind == "funder"
        else "id, name, slug, registry_status, org_kind, legal_form, registration_date, cohort, website, "
        "aliases, staff_count, staff_count_note, source_type, evidence"
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
        # Its standing bar, which is NOT the same question as whether a call is
        # open. Labelled so a reader cannot mistake "what the funder requires"
        # for "whether anybody qualifies" — nothing here judges an applicant.
        "eligibility (the funder_eligibility document: what it REQUIRES of applicants; not a judgement on any)",
        """
        SELECT id AS document_id, title, as_of, source_url, left(content_md, 1500) AS text
        FROM documents WHERE funder_id = %s AND doc_type = 'funder_eligibility'
        ORDER BY fetched_at DESC NULLS LAST, id DESC LIMIT 1
        """,
    ),
    (
        # Without this section an rfps write is invisible to the catalog-writer's
        # own verification step, and a researcher cannot tell a funder with no
        # calls from a funder nobody has checked. A missing section means NOT
        # RECORDED, as the tool's docstring says of every section.
        "rfps (open calls; requirements here are the CALL's, not the standing bar above)",
        """
        SELECT title, status, deadline, amount_min, amount_max, url FROM rfps
        WHERE funder_id = %s ORDER BY deadline DESC NULLS LAST
        """,
    ),
    (
        "funder_csr_years (amounts in INR)",
        """
        SELECT fiscal_year, prescribed_csr, total_spent, average_net_profit, unspent_transferred,
               local_area_spent, source_name
        FROM funder_csr_years WHERE funder_id = %s ORDER BY fiscal_year
        """,
    ),
    (
        "funder_activity kind='spend' (filed lines, INR; domain and theme are INFERRED unless confirmed)",
        """
        SELECT a.fiscal_year, a.project_name, a.amount, a.outlay, a.partner_name, a.implementation_mode,
               a.designation, d.code AS domain, t.code AS theme, a.classified_by, a.classification_confirmed
        FROM funder_activity a
        LEFT JOIN tags d ON d.id = a.domain_tag_id LEFT JOIN tags t ON t.id = a.theme_tag_id
        WHERE a.funder_id = %s AND a.kind = 'spend' ORDER BY a.fiscal_year, a.id
        """,
    ),
    (
        "funder_activity kind='footprint' (where the work actually ran)",
        """
        SELECT a.fiscal_year, a.name_as_printed, s.name AS state, l.name AS location
        FROM funder_activity a
        LEFT JOIN locations s ON s.id = a.state_location_id LEFT JOIN locations l ON l.id = a.location_id
        WHERE a.funder_id = %s AND a.kind = 'footprint' ORDER BY a.fiscal_year, a.id
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
        ("funder_activity kind='partner' (named partners and grants; an amount, INR, is what the partner "
         "received, and a multi-year grant's whole amount sits on its start year)"),
        """
        SELECT fiscal_year, partner_name, partner_canonical, partner_kind, project_name, outlay, amount,
               start_date, end_date, relationship_status, partner_org_id
        FROM funder_activity WHERE funder_id = %s AND kind = 'partner' ORDER BY fiscal_year, id
        """,
    ),
    (
        "funder_activity kind='programme' (the funder's OWN programme totals; never add them to spend)",
        """
        SELECT a.fiscal_year, p.name AS programme, a.amount, d.code AS domain, t.code AS theme,
               a.classification_confirmed
        FROM funder_activity a JOIN programs p ON p.id = a.program_id
        LEFT JOIN tags d ON d.id = a.domain_tag_id LEFT JOIN tags t ON t.id = a.theme_tag_id
        WHERE a.funder_id = %s AND a.kind = 'programme' ORDER BY a.fiscal_year, p.name
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
        ("org_identifiers (current = 'registered' or 'provisional' with a number; 'applied' is not a "
         "registration; 'check_blocked' is not 'valid')"),
        """
        SELECT id_type, id_value, status, valid_until, application_ref, is_current, source_type, evidence
        FROM org_identifiers WHERE org_id = %s ORDER BY id_type, is_current DESC, id
        """,
    ),
    (
        "org_financials (amounts in INR)",
        """
        SELECT fiscal_year, total_income, program_spend, non_program_spend,
               foreign_contribution, foreign_unspent, is_audited, source_type, evidence
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
        "funder_activity kind='partner' naming this organisation (grants received; amount INR)",
        """
        SELECT a.fiscal_year, f.name AS funder, a.project_name, a.amount, a.relationship_status,
               a.start_date, a.end_date
        FROM funder_activity a JOIN funders f ON f.id = a.funder_id
        WHERE a.partner_org_id = %s AND a.kind = 'partner' ORDER BY a.fiscal_year, a.id
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
    which is how an NGO ended up aimed at the funder tables.
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
                "a Section 135 obligation. Every concept below promotes, and every finding names "
                "its source_type and evidence_tier: a blank is always filled, a stronger source "
                "replaces a weaker one, and any other disagreement is kept and reported as a conflict."
            )
        for concept in wanted_concepts:
            spec = CONCEPTS[concept]
            target = spec.table + (f" ({spec.row_filter[0]}='{spec.row_filter[1]}')" if spec.row_filter else "")
            fields = expected_fields(concept)
            count, seen_years = held.get(concept, (0, []))
            state = f"{count} row(s) held" if count else "NOT RECORDED"
            if seen_years:
                missing = [y for y in wanted if y not in seen_years]
                state += f", years {', '.join(sorted(seen_years))}"
                state += f" — still missing {', '.join(missing)}" if missing else " — years covered"
            out.append(f"\n{concept} -> {target}: {state}")
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
        spec = CONCEPTS[concept]
        table = spec.table
        # The entity's own row, which is the match we already have in hand.
        if table == entity_table:
            out[concept] = (1, [])
            continue
        has_year = any(c.name == "fiscal_year" for c in CATALOG[table].columns)
        years = ", array_agg(DISTINCT fiscal_year)" if has_year else ", '{}'::text[]"
        # funder_activity hangs off the funder; an NGO's lines are the ones naming it as the partner.
        col = "partner_org_id" if entity_kind == "org" and table == "funder_activity" else fk
        # Table, column and filter column come from module constants, never a caller.
        where, params = f"{col} = %s", [entity_id]
        if spec.row_filter:
            where += f" AND {spec.row_filter[0]} = %s"
            params.append(spec.row_filter[1])
        found = await (
            await conn.execute(
                f"SELECT count(*) AS n{years} AS years FROM {table} WHERE {where}", tuple(params)
            )
        ).fetchone()
        out[concept] = (found["n"], [y for y in (found["years"] or []) if y])
    return out


@tool
async def promote_research(slug: str = "") -> str:
    """Move saved research into the catalog, where a writer exists for it.

    Research and the catalog are different: a finding is what a source said,
    a catalog row is what the product answers from. This is the step between.

    Works on either kind. A funder's findings reach funders
    and the funder fact tables; an NGO's reach orgs, org_identifiers,
    org_financials and org_locations under the evidence-tier precedence rule —
    a weaker source never overwrites a stronger one, and a disagreement is
    reported as a conflict with both values and both sources, never resolved
    silently. Both kinds write the shared
    programmes, metrics, contacts and documents. A grant is a partner line,
    linked to the organisation only when the matcher would merge the name, and
    anything held back is reported rather than silently dropped. A name that resembles an organisation we already hold
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
            if r["entity"]:
                e = r["entity"]
                years = ", ".join(f"{y['fiscal_year']} {y['status']}" for y in r["csr_years"])
                lines.append(
                    f"  {e['name']}: {e['kind']} {e['status']} [{e['kind']}:{e['id']}]"
                    + (f" · CSR years {years}" if years else "")
                )
            for table, counts in sorted(r.get("written", {}).items()):
                tally = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
                lines.append(f"    {table}: {tally}")
            for reason in r["reasons"]:
                lines.append(f"  {r['slug']}: not promoted — {reason}")
            for held in r.get("held", []):
                lines.append(f"    held back: {held}")
            for conflict in r.get("conflicts", []):
                lines.append(f"    conflict: {conflict}")
            if r["skipped"]:
                skipped = ", ".join(f"{n} {c}" for c, n in sorted(r["skipped"].items()))
                lines.append(f"    still research only (no writer): {skipped}")
        lines.append(
            "\nA grant is a partner line on the funder: linked to the organisation only when the "
            "name matches one we hold, never on a resemblance. Anything held back is named above: "
            "it is a decision waiting for a person, not a silent loss."
        )
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("promote_research failed")
        return f"promote_research failed: {type(exc).__name__}: {exc}"


@tool
async def record_registry_check(
    org: str,
    id_type: str,
    status: str,
    source_url: str,
    id_value: str = "",
    application_ref: str = "",
    evidence_document_id: int | None = None,
    note: str = "",
    checked_on: str = "",
) -> str:
    """Record a registry check a staff member made by hand. Staff only; it writes one catalog row.

    Use it only when the staff member tells you what THEY saw on a registry Sangam cannot read
    (a CAPTCHA, a sign-in or a network filter in the way). Never record a check from your own
    reading or a researcher's: research is not a check. The checker is the signed-in staff member
    of this conversation, never an argument.

    The check is ranked like any other source: level with a registry read, above everything
    else. Registrations lapse, so a NEWER check replaces a dated registry read or manual check
    with a different status; an older or undated one is kept and the difference reported as a
    conflict. A newer check that AGREES updates the row's check date and checker; recorded again
    with a document (same date or later) it upgrades claimed to evidenced. A row a person entered
    (no tier) is never replaced. `check_blocked` never replaces a real status, whatever its date;
    the attempt is noted on the row.

    Args:
        org: the organisation's slug, its exact name, or its id from [org:N].
        id_type: pan, 12a, 80g, fcra, csr1, darpan, cin or reg_no.
        status: registered, provisional, expired, suspended, cancelled, surrendered (these need
            the number), applied (needs the number or application_ref; applied is NOT registered),
            not_available, not_found (the registry was read and does not list it), or
            check_blocked (it could not be read even by hand; never not_found, never valid).
        source_url: the http(s) address of the registry page that was checked.
        id_value: the registration number. Omit to use the one number already on file.
        application_ref: for 'applied', the acknowledgement number (e.g. Form 10AB).
        evidence_document_id: the id of a document uploaded to THIS organisation's Doc Vault
            showing what was seen (a screenshot, a certificate). With it the check is evidenced;
            without it the check is stored as claimed, and the reply says so.
        note: what was checked, where and how, in the staff member's words.
        checked_on: the date the staff member checked, as 2026-10-08. Omit for today.
    """
    try:
        return await manual_checks.record(
            get_pool(), org=org, id_type=id_type, status=status, source_url=source_url, id_value=id_value,
            application_ref=application_ref, document_id=evidence_document_id, note=note,
            checked_on=checked_on, user_id=chat_user_id.get(),
        )
    except Exception as exc:
        logger.exception("record_registry_check failed")
        return f"record_registry_check failed: {type(exc).__name__}: {exc}"
