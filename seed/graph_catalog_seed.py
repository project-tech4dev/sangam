"""Write Sangam's catalog into the knowledge graph as typed nodes and edges, with no model call.

Orgs, funders, places, programmes and the theme taxonomy become nodes with fixed uuids, so a
re-run updates in place and documents added later fold into them. Reads Postgres, writes Neo4j only.

    python -m seed.graph_catalog_seed [group_id]
Requires NEO4J_URI and OPENAI_API_KEY (embeddings).
"""

from __future__ import annotations

import asyncio
import os
import sys


async def sync(database_url: str, group_id: str) -> dict:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from app.core.config import get_settings
    from app.integrations.graphiti import graph_status, open_graph
    from app.repositories.graph_catalog import sync_catalog

    settings = get_settings()
    status = graph_status(settings)
    if status != "ok":
        sys.exit(f"knowledge graph not configured: {status}")
    client = await open_graph(settings)
    if client is None:
        sys.exit(f"could not open the knowledge graph at {settings.neo4j_uri}")
    try:
        async with AsyncConnectionPool(database_url, kwargs={"row_factory": dict_row}, min_size=1, max_size=1,
                                       open=False) as pool:
            return await sync_catalog(client, pool, group_id=group_id)
    finally:
        await client.close()


def main() -> None:
    from app.integrations.graph_ontology import DEFAULT_GROUP

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set")
    result = asyncio.run(sync(database_url, sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GROUP))
    print(f"graph seed complete: {result}")


if __name__ == "__main__":
    main()
