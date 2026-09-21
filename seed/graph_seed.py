"""Build the Graphiti knowledge graph from Postgres (the system of record).

Reads funder profiles, org registrations, and the hand-vetting adjustment log,
and ingests each as a Graphiti "episode"; Graphiti's LLM extracts entities and
temporal relationship edges into FalkorDB. Re-runnable: episodes are named
deterministically, and the graph can always be dropped and rebuilt from here.

Run inside the backend container:
    python -m seed.graph_seed
Requires FALKORDB_HOST and OPENAI_API_KEY (Graphiti extraction + embeddings).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def collect_episodes(database_url: str) -> list[dict]:
    episodes: list[dict] = []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        funders = conn.execute(
            "SELECT name, funder_type, focus_sectors, geographies, profile FROM funders"
        ).fetchall()
        for f in funders:
            profile_lines = "\n".join(f"{k}: {v}" for k, v in (f["profile"] or {}).items())
            episodes.append(
                {
                    "name": f"funder-profile-{f['name']}",
                    "body": (
                        f"{f['name']} is a {f['funder_type']} funder. "
                        f"Focus sectors: {', '.join(f['focus_sectors'])}. "
                        f"Geographies: {', '.join(f['geographies'])}.\n{profile_lines}"
                    ),
                    "description": "funder profile (hand-vetting research)",
                }
            )

        orgs = conn.execute(
            """
            SELECT name, state, district, sectors, registration
            FROM orgs WHERE slug IN ('kabil', 'bdf')
            """
        ).fetchall()
        for o in orgs:
            reg_lines = "\n".join(f"{k}: {v}" for k, v in (o["registration"] or {}).items())
            episodes.append(
                {
                    "name": f"org-profile-{o['name']}",
                    "body": (
                        f"{o['name']} is a civil-society organisation based in "
                        f"{o['district']}, {o['state']}. "
                        f"Sectors: {', '.join(o['sectors'])}.\n{reg_lines}"
                    ),
                    "description": "organisation profile (hand-vetting fact-check)",
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

    from app.config import get_settings
    from app.graph import graph_status, open_graph

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
                reference_time=ep.get("reference_time") or datetime.now(timezone.utc),
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
