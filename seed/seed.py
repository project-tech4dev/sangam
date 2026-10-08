"""Idempotent seed script (schema v2): vocabularies, darpan orgs, hand-vetted
funders, programs, grants, rubrics, KABIL fit scores + adjustments, GDELT news.

Run inside the backend container (or any env with DATABASE_URL set):
    python -m seed.seed
Re-running is safe: upserts on natural keys.

ORDER INVARIANT (do not reorder): darpan orgs from the sorted glob first, then
orgs_extra.json in file order, then funders.json in file order. Restored
`documents` rows reference orgs 1-10 / funders 1-4 by these seed-order ids;
changing insertion order silently mislinks them (make db-upgrade diffs the
linkage projection to catch this).
"""

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DATA = Path(__file__).parent / "data"
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
EXTRACTOR_VERSION = "seed-v2"

# Geography names appearing in seed data that are not districts of Assam.
LOCATION_KINDS = {"India": "country", "Northeast India": "region", "Assam": "state"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]


def parse_date(value) -> str | None:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --- Phase 1: vocabularies -------------------------------------------------


def _upsert_location(cur, kind: str, name: str, parent_id=None) -> int:
    cur.execute(
        """
        INSERT INTO locations (kind, name, parent_id) VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (kind, name, parent_id),
    )
    cur.execute(
        "SELECT id FROM locations WHERE kind = %s AND name = %s AND parent_id IS NOT DISTINCT FROM %s",
        (kind, name, parent_id),
    )
    return cur.fetchone()[0]


def seed_vocabularies(cur) -> tuple[dict[str, int], dict[str, int]]:
    """Upsert the locations hierarchy and tag vocabulary; return lookup maps."""
    india = _upsert_location(cur, "country", "India")
    assam = _upsert_location(cur, "state", "Assam", india)
    ne = _upsert_location(cur, "region", "Northeast India", india)
    locations = {"India": india, "Assam": assam, "Northeast India": ne}

    # (district, state) — the state matters: DIMAPUR is in Nagaland, and
    # parenting it to Assam made every state-level rollup through parent_id
    # wrong for it. Darpan states the state; this used to ignore it.
    district_names: set[tuple[str, str]] = set()
    tag_labels: set[str] = set()

    for path in sorted((DATA / "darpan").glob("*.json")):
        raw = json.loads(path.read_text())
        sections = raw.get("sections", {})
        registration = sections.get("registration_details", {}) or {}
        city = registration.get("city_of_registration")
        if city:
            state_name = str(registration.get("state_of_registration") or "Assam").strip()
            # preserve source casing (e.g. CHIRANG)
            district_names.add((str(city).strip(), state_name))
        working = sections.get("working_sectors", {}) or {}
        tag_labels.update(as_list(working.get("primary_sectors")))
        tag_labels.update(as_list(working.get("secondary_sectors")))

    for org in json.loads((DATA / "rubrics" / "orgs_extra.json").read_text()):
        if org.get("district"):
            district_names.add((org["district"], org.get("state") or "Assam"))
        tag_labels.update(org.get("sectors", []))

    for funder in json.loads((DATA / "rubrics" / "funders.json").read_text()):
        tag_labels.update(funder.get("focus_sectors", []))
        for geo in funder.get("geographies", []):
            if geo not in LOCATION_KINDS:
                district_names.add((geo, "Assam"))

    for name, state_name in sorted(district_names):
        parent = locations.get(state_name)
        if parent is None:
            parent = locations[state_name] = _upsert_location(cur, "state", state_name, india)
        locations[name] = _upsert_location(cur, "district", name, parent)

    tags: dict[str, int] = {}
    for label in sorted(tag_labels):
        slug = slugify(label)
        cur.execute(
            """
            INSERT INTO tags (slug, label, kind) VALUES (%s, %s, 'sector')
            ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label
            RETURNING id
            """,
            (slug, label),
        )
        tags[slug] = cur.fetchone()[0]
    return locations, tags


# --- Shared helpers ---------------------------------------------------------


def _upsert_org_identifiers(cur, org_id: int, identifiers: dict[str, str], source_url: str | None):
    for id_type, id_value in identifiers.items():
        if not id_value:
            continue
        cur.execute(
            """
            INSERT INTO org_identifiers (org_id, id_type, id_value, verified, source_url)
            VALUES (%s, %s, %s, true, %s)
            ON CONFLICT (id_type, id_value) DO NOTHING
            """,
            (org_id, id_type, str(id_value), source_url),
        )


def _upsert_org_tags(cur, org_id: int, tags: dict[str, int], labels_by_role: dict[str, str]):
    """labels_by_role: {label: role}; primary wins if a label appears twice upstream."""
    for label, role in labels_by_role.items():
        tag_id = tags.get(slugify(label))
        if tag_id is None:
            continue
        cur.execute(
            """
            INSERT INTO org_tags (org_id, tag_id, role) VALUES (%s, %s, %s)
            ON CONFLICT (org_id, tag_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (org_id, tag_id, role),
        )


def _upsert_org_location(cur, org_id: int, location_id: int | None, role: str = "operates"):
    if location_id is None:
        return
    cur.execute(
        """
        INSERT INTO org_locations (org_id, location_id, role) VALUES (%s, %s, %s)
        ON CONFLICT (org_id, location_id) DO UPDATE SET role = EXCLUDED.role
        """,
        (org_id, location_id, role),
    )


def _upsert_contact(cur, *, org_id=None, funder_id=None, name, role, kind, email=None,
                    phone=None, source_name=None, source_url=None):
    owner_col = "org_id" if org_id is not None else "funder_id"
    cur.execute(
        f"""
        INSERT INTO contacts ({owner_col}, name, role, kind, email, phone, source_name, source_url, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT ({owner_col}, name, role) WHERE {owner_col} IS NOT NULL DO NOTHING
        """,
        (org_id if org_id is not None else funder_id, name, role, kind, email, phone,
         source_name, source_url),
    )


# --- Phase 2/3: orgs --------------------------------------------------------


def seed_darpan_orgs(cur, locations, tags) -> int:
    count = 0
    for path in sorted((DATA / "darpan").glob("*.json")):  # ORDER INVARIANT
        raw = json.loads(path.read_text())
        sections = raw.get("sections", {})
        reg = sections.get("registration_details", {}) or {}
        contact = sections.get("contact_details", {}) or {}
        working = sections.get("working_sectors", {}) or {}
        slug = path.stem.removeprefix("ngo-darpan-")
        district_id = locations.get(str(reg.get("city_of_registration", "")).strip())
        cur.execute(
            """
            INSERT INTO orgs (slug, name, org_kind, cohort, legal_form, registration_date,
                              registered_location_id, contact, sections,
                              source_url, source_name, content_hash, extractor_version)
            VALUES (%s, %s, 'cso', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, cohort = EXCLUDED.cohort,
              legal_form = EXCLUDED.legal_form, registration_date = EXCLUDED.registration_date,
              registered_location_id = EXCLUDED.registered_location_id,
              contact = EXCLUDED.contact, sections = EXCLUDED.sections,
              source_url = EXCLUDED.source_url, source_name = EXCLUDED.source_name,
              content_hash = EXCLUDED.content_hash, extractor_version = EXCLUDED.extractor_version
            RETURNING id
            """,
            (
                slug,
                raw.get("entity_name") or slug,
                raw.get("cohort"),
                reg.get("type_of_npo"),
                parse_date(reg.get("date_of_registration_society_trust_entity")),
                district_id,
                json.dumps(contact),
                json.dumps(sections),
                raw.get("source_url"),
                raw.get("source", "darpan-portal"),
                sha256(path),
                EXTRACTOR_VERSION,
            ),
        )
        org_id = cur.fetchone()[0]
        _upsert_org_identifiers(
            cur, org_id,
            {"darpan": raw.get("darpan_id"), "reg_no": reg.get("registration_no")},
            raw.get("source_url"),
        )
        labels: dict[str, str] = {}
        for label in as_list(working.get("secondary_sectors")):
            labels[label] = "secondary"
        for label in as_list(working.get("primary_sectors")):
            labels[label] = "primary"  # primary wins on overlap
        _upsert_org_tags(cur, org_id, tags, labels)
        _upsert_org_location(cur, org_id, district_id, "operates")
        for bearer in sections.get("office_bearers", []) or []:
            if bearer.get("name"):
                _upsert_contact(
                    cur, org_id=org_id, name=bearer["name"], role=bearer.get("designation"),
                    kind="office_bearer", source_name=raw.get("source", "darpan-portal"),
                    source_url=raw.get("source_url"),
                )
        count += 1
    return count


def seed_extra_orgs(cur, locations, tags) -> int:
    extras = json.loads((DATA / "rubrics" / "orgs_extra.json").read_text())  # ORDER INVARIANT
    for org in extras:
        reg = org.get("registration", {}) or {}
        district_id = locations.get(org.get("district"))
        cur.execute(
            """
            INSERT INTO orgs (slug, name, org_kind, cohort, legal_form, registration_date,
                              registered_location_id, contact,
                              source_url, source_name, fetched_at, extractor_version)
            VALUES (%s, %s, 'cso', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, cohort = EXCLUDED.cohort,
              legal_form = EXCLUDED.legal_form, registration_date = EXCLUDED.registration_date,
              registered_location_id = EXCLUDED.registered_location_id,
              contact = EXCLUDED.contact, source_url = EXCLUDED.source_url,
              source_name = EXCLUDED.source_name, fetched_at = EXCLUDED.fetched_at,
              extractor_version = EXCLUDED.extractor_version
            RETURNING id
            """,
            (
                org["slug"], org["name"], org.get("cohort"),
                reg.get("legal_form"), parse_date(reg.get("registration_date")),
                district_id, json.dumps(org.get("contact", {})),
                org.get("source_url"), org.get("source_name"),
                org.get("fetched_at"), EXTRACTOR_VERSION,
            ),
        )
        org_id = cur.fetchone()[0]
        _upsert_org_identifiers(
            cur, org_id,
            {
                "pan": reg.get("pan"), "12a": reg.get("12a"), "80g": reg.get("80g"),
                "fcra": reg.get("fcra"), "reg_no": reg.get("registration_no"),
                # csr1 deliberately skipped: 'Not Available' is a finding, not an identifier
            },
            org.get("source_url"),
        )
        _upsert_org_tags(cur, org_id, tags, {label: "primary" for label in org.get("sectors", [])})
        _upsert_org_location(cur, org_id, district_id, "operates")
    return len(extras)


# --- Phase 4: funders -------------------------------------------------------


def seed_funders(cur, locations, tags) -> int:
    funders = json.loads((DATA / "rubrics" / "funders.json").read_text())  # ORDER INVARIANT
    for funder in funders:
        profile = dict(funder.get("profile", {}))
        section_135 = profile.pop("section_135_bound", None)
        cur.execute(
            """
            INSERT INTO funders (slug, name, funder_type, section_135_bound, website,
                                 profile, source_url, source_name, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name, funder_type = EXCLUDED.funder_type,
              section_135_bound = EXCLUDED.section_135_bound, website = EXCLUDED.website,
              profile = EXCLUDED.profile, source_url = EXCLUDED.source_url,
              source_name = EXCLUDED.source_name, extractor_version = EXCLUDED.extractor_version
            RETURNING id
            """,
            (
                funder["slug"], funder["name"], funder.get("funder_type"), section_135,
                funder.get("website"), json.dumps(profile),
                funder.get("source_url"), funder.get("source_name"), EXTRACTOR_VERSION,
            ),
        )
        funder_id = cur.fetchone()[0]
        for label in funder.get("focus_sectors", []):
            tag_id = tags.get(slugify(label))
            if tag_id is not None:
                cur.execute(
                    """
                    INSERT INTO funder_tags (funder_id, tag_id, role) VALUES (%s, %s, 'primary')
                    ON CONFLICT (funder_id, tag_id) DO NOTHING
                    """,
                    (funder_id, tag_id),
                )
        for geo in funder.get("geographies", []):
            loc_id = locations.get(geo)
            if loc_id is not None:
                cur.execute(
                    """
                    INSERT INTO funder_locations (funder_id, location_id, role)
                    VALUES (%s, %s, 'funds')
                    ON CONFLICT (funder_id, location_id) DO NOTHING
                    """,
                    (funder_id, loc_id),
                )
    return len(funders)


# --- Phase 5/6: programs + grants ------------------------------------------


def lookup_id(cur, table: str, key: str, value: str) -> int:
    cur.execute(f"SELECT id FROM {table} WHERE {key} = %s", (value,))  # noqa: S608 - fixed identifiers
    row = cur.fetchone()
    if row is None:
        sys.exit(f"seed error: no {table} row with {key}={value!r}")
    return row[0]


def seed_programs(cur) -> dict[tuple[int, str], int]:
    programs = json.loads((DATA / "programs.json").read_text())
    ids: dict[tuple[int, str], int] = {}
    for program in programs:
        funder_id = lookup_id(cur, "funders", "slug", program["owner_funder"])
        cur.execute(
            """
            INSERT INTO programs (funder_id, name, description, status, details,
                                  source_url, source_name, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (funder_id, name) WHERE funder_id IS NOT NULL DO UPDATE SET
              description = EXCLUDED.description, status = EXCLUDED.status,
              details = EXCLUDED.details, source_url = EXCLUDED.source_url
            RETURNING id
            """,
            (
                funder_id, program["name"], program.get("description"), program.get("status"),
                json.dumps(program.get("details", {})),
                program.get("source_url"), program.get("source_name"), EXTRACTOR_VERSION,
            ),
        )
        ids[(funder_id, program["name"])] = cur.fetchone()[0]
    return ids


def seed_grants(cur, program_ids) -> int:
    grants = json.loads((DATA / "grants.json").read_text())
    for grant in grants:
        funder_id = lookup_id(cur, "funders", "slug", grant["funder"])
        org_id = lookup_id(cur, "orgs", "slug", grant["org"])
        program_id = program_ids.get((funder_id, grant["program"])) if grant.get("program") else None
        cur.execute(
            """
            INSERT INTO grants (funder_id, org_id, program_id, title, start_date, end_date,
                                status, outcomes, notes, source_url, source_name,
                                fetched_at, extractor_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (funder_id, org_id, title) DO UPDATE SET
              program_id = EXCLUDED.program_id, start_date = EXCLUDED.start_date,
              end_date = EXCLUDED.end_date, status = EXCLUDED.status,
              outcomes = EXCLUDED.outcomes, notes = EXCLUDED.notes,
              source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at
            """,
            (
                funder_id, org_id, program_id, grant["title"],
                grant.get("start_date"), grant.get("end_date"), grant["status"],
                json.dumps(grant.get("outcomes", {})), grant.get("notes"),
                grant.get("source_url"), grant.get("source_name"),
                grant.get("fetched_at"), EXTRACTOR_VERSION,
            ),
        )
    return len(grants)


# --- Phase 7: rubrics / scores / news (unchanged from v1) -------------------


def seed_rubrics(cur) -> dict[tuple[str, str], int]:
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
        locations, tags = seed_vocabularies(cur)
        n_darpan = seed_darpan_orgs(cur, locations, tags)
        n_extra = seed_extra_orgs(cur, locations, tags)
        n_funders = seed_funders(cur, locations, tags)
        program_ids = seed_programs(cur)
        n_grants = seed_grants(cur, program_ids)
        criterion_ids = seed_rubrics(cur)
        n_scores, n_items = seed_scores(cur, criterion_ids)
        n_news = seed_news(cur)
        conn.commit()
    print(
        f"seeded: {len(locations)} locations, {len(tags)} tags, "
        f"{n_darpan}+{n_extra} orgs, {n_funders} funders, {len(program_ids)} programs, "
        f"{n_grants} grants, {len(criterion_ids)} rubric criteria, "
        f"{n_scores} fit scores ({n_items} items), {n_news} news mentions"
    )


if __name__ == "__main__":
    main()
