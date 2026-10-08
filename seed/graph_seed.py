"""Build the Graphiti knowledge graph from Postgres (the system of record).

Reads funder profiles, org registrations, and the hand-vetting adjustment log,
and ingests each as a Graphiti "episode"; Graphiti's LLM extracts entities and
temporal relationship edges into FalkorDB. Re-runnable: episodes are named
deterministically, and the graph can always be dropped and rebuilt from here.

Run inside the backend container:
    python -m seed.graph_seed
Requires NEO4J_URI and OPENAI_API_KEY (Graphiti extraction + embeddings).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row


def collect_episodes(database_url: str) -> list[dict]:
    episodes: list[dict] = []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        funders = conn.execute(
            """
            SELECT f.name, f.funder_type, f.section_135_bound, f.profile,
                   COALESCE(t.sectors, '{}') AS focus_sectors,
                   COALESCE(l.geos, '{}') AS geographies
            FROM funders f
            LEFT JOIN LATERAL (
              SELECT array_agg(tg.label) AS sectors FROM funder_tags ft
              JOIN tags tg ON tg.id = ft.tag_id WHERE ft.funder_id = f.id
            ) t ON true
            LEFT JOIN LATERAL (
              SELECT array_agg(lo.name) AS geos FROM funder_locations fl
              JOIN locations lo ON lo.id = fl.location_id WHERE fl.funder_id = f.id
            ) l ON true
            ORDER BY f.id
            """
        ).fetchall()
        for f in funders:
            profile_lines = "\n".join(f"{k}: {v}" for k, v in (f["profile"] or {}).items())
            section = ("It is a Section-135-bound CSR funder." if f["section_135_bound"]
                       else "It is not Section-135-bound." if f["section_135_bound"] is False else "")
            episodes.append(
                {
                    "name": f"funder-profile-{f['name']}",
                    "body": (
                        f"{f['name']} is a {f['funder_type']} funder. {section} "
                        f"Focus sectors: {', '.join(f['focus_sectors'])}. "
                        f"Geographies: {', '.join(f['geographies'])}.\n{profile_lines}"
                    ),
                    "description": "funder profile (hand-vetting research)",
                }
            )

        orgs = conn.execute(
            """
            SELECT o.name, o.legal_form, o.registration_date,
                   dl.name AS district, sl.name AS state,
                   COALESCE(t.sectors, '{}') AS sectors,
                   COALESCE(i.ids, '') AS ids
            FROM orgs o
            LEFT JOIN locations dl ON dl.id = o.registered_location_id
            LEFT JOIN locations sl ON sl.id = dl.parent_id
            LEFT JOIN LATERAL (
              SELECT array_agg(tg.label) AS sectors FROM org_tags ot
              JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = o.id
            ) t ON true
            LEFT JOIN LATERAL (
              SELECT string_agg(upper(oi.id_type) || ' ' || oi.id_value, ', ') AS ids
              FROM org_identifiers oi WHERE oi.org_id = o.id AND oi.id_value IS NOT NULL
            ) i ON true
            WHERE o.slug IN ('kabil', 'bdf')
            ORDER BY o.id
            """
        ).fetchall()
        for o in orgs:
            episodes.append(
                {
                    "name": f"org-profile-{o['name']}",
                    "body": (
                        f"{o['name']} is a civil-society organisation ({o['legal_form']}, "
                        f"registered {o['registration_date']}) based in {o['district']}, {o['state']}. "
                        f"Sectors: {', '.join(o['sectors'])}. Registrations: {o['ids']}."
                    ),
                    "description": "organisation profile (hand-vetting fact-check)",
                }
            )

        grant_lines = conn.execute(
            """
            SELECT a.project_name AS title, a.relationship_status AS status, a.start_date, a.end_date,
                   a.notes, f.name AS funder_name, o.name AS org_name, p.name AS program_name
            FROM funder_activity a
            JOIN funders f ON f.id = a.funder_id
            JOIN orgs o ON o.id = a.partner_org_id
            LEFT JOIN programs p ON p.id = a.program_id
            WHERE a.kind = 'partner' AND a.project_name IS NOT NULL
            ORDER BY a.id
            """
        ).fetchall()
        # The episode name is unchanged from the grants table's, so an ingested episode is recognised.
        for g in grant_lines:
            dates = (f" from {g['start_date']} to {g['end_date']}"
                     if g["start_date"] else "")
            episodes.append(
                {
                    "name": f"grant-{g['funder_name']}-{g['org_name']}-{g['title'][:30]}",
                    "body": (
                        f"{g['funder_name']} funded {g['org_name']}: {g['title']}"
                        + (f" under the {g['program_name']} program" if g["program_name"] else "")
                        + f"{dates}. Status: {g['status'] or 'not stated'}."
                        + (f" {g['notes']}" if g["notes"] else "")
                    ),
                    "description": "funding relationship (funder_activity partner line)",
                }
            )

        adjustments = conn.execute(
            """
            SELECT o.name AS org_name, f.name AS funder_name, rc.label, sa.reason, sa.adjusted_at
            FROM score_adjustments sa
            JOIN fit_scores fs ON fs.id = sa.fit_score_id
            JOIN orgs o ON o.id = fs.org_id
            JOIN funders f ON f.id = fs.funder_id
            JOIN rubric_criteria rc ON rc.id = sa.criterion_id
            """
        ).fetchall()
        for a in adjustments:
            episodes.append(
                {
                    "name": f"vetting-{a['org_name']}-{a['funder_name']}-{a['label'][:20]}",
                    "body": (
                        f"Hand-vetting finding about {a['org_name']} and {a['funder_name']} "
                        f"({a['label']}): {a['reason']}"
                    ),
                    "description": "hand-vetting adjustment log",
                    "reference_time": a["adjusted_at"],
                }
            )
    return episodes


async def ingest(episodes: list[dict]) -> None:
    from graphiti_core.nodes import EpisodeType

    from app.core.config import get_settings
    from app.integrations.graphiti import graph_status, open_graph

    settings = get_settings()
    status = graph_status(settings)
    if status != "ok":
        sys.exit(f"knowledge graph not configured: {status}")
    client = await open_graph(settings)
    try:
        for i, ep in enumerate(episodes, 1):
            await client.add_episode(
                name=ep["name"],
                episode_body=ep["body"],
                source=EpisodeType.text,
                source_description=ep["description"],
                reference_time=ep.get("reference_time") or datetime.now(UTC),
            )
            print(f"[{i}/{len(episodes)}] ingested: {ep['name']}")
    finally:
        await client.close()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set")
    episodes = collect_episodes(database_url)
    print(f"collected {len(episodes)} episodes from Postgres")
    asyncio.run(ingest(episodes))
    print("graph seed complete")


if __name__ == "__main__":
    main()
