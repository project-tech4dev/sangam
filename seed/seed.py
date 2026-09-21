"""Idempotent seed script: darpan orgs, hand-vetted funders, rubrics, KABIL fit
scores + adjustment audit log, and GDELT news mentions.

Run inside the backend container (or any env with DATABASE_URL set):
    python -m seed.seed
Re-running is safe: upserts on natural keys (slug, darpan_id, url, rubric version).
"""

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DATA = Path(__file__).parent / "data"
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
EXTRACTOR_VERSION = "seed-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]


def seed_darpan_orgs(cur) -> int:
    count = 0
    for path in sorted((DATA / "darpan").glob("*.json")):
        raw = json.loads(path.read_text())
        sections = raw.get("sections", {})
        reg = sections.get("registration_details", {})
        contact = sections.get("contact_details", {})
        working = sections.get("working_sectors", {})
        sectors = as_list(working.get("primary_sectors")) + as_list(working.get("secondary_sectors"))
        slug = path.stem.removeprefix("ngo-darpan-")
        cur.execute(
            """
            INSERT INTO orgs (slug, name, darpan_id, cohort, state, district,
                              registration, contact, sectors, sections,
                              source_url, source_name, content_hash, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, darpan_id = EXCLUDED.darpan_id,
              cohort = EXCLUDED.cohort, state = EXCLUDED.state, district = EXCLUDED.district,
              registration = EXCLUDED.registration, contact = EXCLUDED.contact,
              sectors = EXCLUDED.sectors, sections = EXCLUDED.sections,
              source_url = EXCLUDED.source_url, source_name = EXCLUDED.source_name,
              content_hash = EXCLUDED.content_hash, extractor_version = EXCLUDED.extractor_version
            RETURNING id
            """,
            (
                slug,
                raw.get("entity_name") or slug,
                raw.get("darpan_id"),
                raw.get("cohort"),
                reg.get("state_of_registration"),
                reg.get("city_of_registration"),
                json.dumps(reg),
                json.dumps(contact),
                sectors,
                json.dumps(sections),
                raw.get("source_url"),
                raw.get("source", "darpan-portal"),
                sha256(path),
                EXTRACTOR_VERSION,
            ),
        )
        org_id = cur.fetchone()[0]
        for bearer in sections.get("office_bearers", []):
            if bearer.get("name"):
                cur.execute(
                    """
                    INSERT INTO org_office_bearers (org_id, name, designation)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (org_id, name, designation) DO NOTHING
                    """,
                    (org_id, bearer["name"], bearer.get("designation")),
                )
        count += 1
    return count


def seed_extra_orgs(cur) -> int:
    extras = json.loads((DATA / "rubrics" / "orgs_extra.json").read_text())
    for org in extras:
        cur.execute(
            """
            INSERT INTO orgs (slug, name, cohort, state, district,
                              registration, contact, sectors,
                              source_url, source_name, fetched_at, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, cohort = EXCLUDED.cohort,
              state = EXCLUDED.state, district = EXCLUDED.district,
              registration = EXCLUDED.registration, contact = EXCLUDED.contact,
              sectors = EXCLUDED.sectors, source_url = EXCLUDED.source_url,
              source_name = EXCLUDED.source_name, fetched_at = EXCLUDED.fetched_at,
              extractor_version = EXCLUDED.extractor_version
            """,
            (
                org["slug"], org["name"], org.get("cohort"), org.get("state"),
                org.get("district"), json.dumps(org.get("registration", {})),
                json.dumps(org.get("contact", {})), org.get("sectors", []),
                org.get("source_url"), org.get("source_name"),
                org.get("fetched_at"), EXTRACTOR_VERSION,
            ),
        )
    return len(extras)


def seed_funders(cur) -> int:
    funders = json.loads((DATA / "rubrics" / "funders.json").read_text())
    for funder in funders:
        cur.execute(
            """
            INSERT INTO funders (slug, name, funder_type, website, focus_sectors,
                                 geographies, profile, source_url, source_name, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, funder_type = EXCLUDED.funder_type,
              website = EXCLUDED.website, focus_sectors = EXCLUDED.focus_sectors,
              geographies = EXCLUDED.geographies, profile = EXCLUDED.profile,
              source_url = EXCLUDED.source_url, source_name = EXCLUDED.source_name,
              extractor_version = EXCLUDED.extractor_version
            RETURNING id
            """,
            (
                funder["slug"], funder["name"], funder.get("funder_type"),
                funder.get("website"), funder.get("focus_sectors", []),
                funder.get("geographies", []), json.dumps(funder.get("profile", {})),
                funder.get("source_url"), funder.get("source_name"), EXTRACTOR_VERSION,
            ),
        )
        funder_id = cur.fetchone()[0]
        if funder.get("website"):
            domain = funder["website"].split("//")[-1].split("/")[0].removeprefix("www.")
            cur.execute(
                """
                INSERT INTO funder_aliases (funder_id, alias_type, alias_value)
                VALUES (%s, 'domain', %s)
                ON CONFLICT (alias_type, alias_value) DO NOTHING
                """,
                (funder_id, domain),
            )
    return len(funders)


def seed_rubrics(cur) -> dict[tuple[str, str], int]:
    """Insert rubrics + criteria; return {(version, code): criterion_id}."""
    criterion_ids: dict[tuple[str, str], int] = {}
    for version_file in ("v1.json", "v2.json"):
        rubric = json.loads((DATA / "rubrics" / version_file).read_text())
        cur.execute(
            """
            INSERT INTO rubrics (version, name, total_points, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (version) DO UPDATE SET
              name = EXCLUDED.name, total_points = EXCLUDED.total_points, notes = EXCLUDED.notes
            RETURNING id
            """,
            (rubric["version"], rubric["name"], rubric["total_points"], rubric.get("notes")),
        )
        rubric_id = cur.fetchone()[0]
        # Two passes so parents exist before children reference them.
        criteria = rubric["criteria"]
        for criterion in [c for c in criteria if not c.get("parent")] + [c for c in criteria if c.get("parent")]:
            parent_id = criterion_ids.get((rubric["version"], criterion["parent"])) if criterion.get("parent") else None
            cur.execute(
                """
                INSERT INTO rubric_criteria (rubric_id, parent_id, code, label, points, guiding_question)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rubric_id, code) DO UPDATE SET
                  parent_id = EXCLUDED.parent_id, label = EXCLUDED.label,
                  points = EXCLUDED.points, guiding_question = EXCLUDED.guiding_question
                RETURNING id
                """,
                (rubric_id, parent_id, criterion["code"], criterion["label"],
                 criterion["points"], criterion.get("guiding_question")),
            )
            criterion_ids[(rubric["version"], criterion["code"])] = cur.fetchone()[0]
    return criterion_ids


def lookup_id(cur, table: str, key: str, value: str) -> int:
    cur.execute(f"SELECT id FROM {table} WHERE {key} = %s", (value,))  # noqa: S608 - fixed identifiers
    row = cur.fetchone()
    if row is None:
        sys.exit(f"seed error: no {table} row with {key}={value!r}")
    return row[0]


def seed_scores(cur, criterion_ids) -> tuple[int, int]:
    scores = json.loads((DATA / "rubrics" / "scores.json").read_text())
    org_id = lookup_id(cur, "orgs", "slug", scores["org"])
    n_scores = n_items = 0
    fit_score_ids: dict[tuple[str, str], int] = {}
    for assessment in scores["assessments"]:
        funder_id = lookup_id(cur, "funders", "slug", assessment["funder"])
        rubric_id = lookup_id(cur, "rubrics", "version", assessment["rubric"])
        cur.execute(
            """
            INSERT INTO fit_scores (org_id, funder_id, rubric_id, total_score, max_score,
                                    scored_by, scored_at, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (org_id, funder_id, rubric_id, scored_at) DO UPDATE SET
              total_score = EXCLUDED.total_score, max_score = EXCLUDED.max_score,
              scored_by = EXCLUDED.scored_by, notes = EXCLUDED.notes
            RETURNING id
            """,
            (org_id, funder_id, rubric_id, assessment["total"], assessment["max"],
             assessment["scored_by"], assessment["scored_at"], assessment.get("notes")),
        )
        fit_score_id = cur.fetchone()[0]
        fit_score_ids[(assessment["rubric"], assessment["funder"])] = fit_score_id
        cur.execute("DELETE FROM fit_score_items WHERE fit_score_id = %s", (fit_score_id,))
        for item in assessment["items"]:
            cur.execute(
                """
                INSERT INTO fit_score_items (fit_score_id, criterion_id, score, justification)
                VALUES (%s, %s, %s, %s)
                """,
                (fit_score_id, criterion_ids[(assessment["rubric"], item["code"])],
                 item["score"], item.get("justification")),
            )
            n_items += 1
        n_scores += 1

    adjustments = json.loads((DATA / "rubrics" / "adjustments.json").read_text())
    for adjustment in adjustments["adjustments"]:
        fit_score_id = fit_score_ids[(adjustments["rubric"], adjustment["funder"])]
        criterion_id = criterion_ids[(adjustments["rubric"], adjustment["code"])]
        cur.execute(
            "DELETE FROM score_adjustments WHERE fit_score_id = %s AND criterion_id = %s",
            (fit_score_id, criterion_id),
        )
        cur.execute(
            """
            INSERT INTO score_adjustments (fit_score_id, criterion_id, old_score, new_score,
                                           reason, adjusted_by, adjusted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (fit_score_id, criterion_id, adjustment["old_score"], adjustment["new_score"],
             adjustment["reason"], DEV_USER_ID, adjustments["adjusted_at"]),
        )
    return n_scores, n_items


def seed_news(cur) -> int:
    count = 0
    for path in sorted((DATA / "gdelt").glob("*.csv")):
        topic = path.stem
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if not row.get("url"):
                    continue
                seendate = None
                if row.get("seendate"):
                    seendate = datetime.strptime(row["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                cur.execute(
                    """
                    INSERT INTO news_mentions (url, title, seendate, domain, language,
                                               sourcecountry, topic, source_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'gdelt')
                    ON CONFLICT (url) DO UPDATE SET
                      title = EXCLUDED.title, seendate = EXCLUDED.seendate, topic = EXCLUDED.topic
                    """,
                    (row["url"], row.get("title"), seendate, row.get("domain"),
                     row.get("language"), row.get("sourcecountry"), topic),
                )
                count += 1
    return count


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        n_darpan = seed_darpan_orgs(cur)
        n_extra = seed_extra_orgs(cur)
        n_funders = seed_funders(cur)
        criterion_ids = seed_rubrics(cur)
        n_scores, n_items = seed_scores(cur, criterion_ids)
        n_news = seed_news(cur)
        conn.commit()
    print(
        f"seeded: {n_darpan} darpan orgs + {n_extra} extra orgs, {n_funders} funders, "
        f"{len(criterion_ids)} rubric criteria, {n_scores} fit scores ({n_items} items), "
        f"{n_news} news mentions"
    )


if __name__ == "__main__":
    main()
