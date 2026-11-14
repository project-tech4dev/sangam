"""Graphiti temporal knowledge graph over Neo4j."""

from __future__ import annotations

import logging

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Set by the lifespan (like app.db.pool); None means graph features are off.
client = None


def graph_status(settings: Settings) -> str:
    if not settings.neo4j_uri:
        return "NEO4J_URI is not set"
    if not settings.openai_api_key:
        return "OPENAI_API_KEY is not set (Graphiti needs it for embeddings/extraction)"
    return "ok"


async def open_graph(settings: Settings):
    """Initialise the Graphiti client, or return None with a logged reason."""
    global client
    status = graph_status(settings)
    if status != "ok":
        logger.warning("Knowledge graph disabled: %s", status)
        return None
    # Imported lazily so the app still boots if graph deps are missing.
    from graphiti_core import Graphiti
    from graphiti_core.driver.neo4j_driver import Neo4jDriver

    graphiti = None
    try:
        database = await _home_database(settings)
        driver = Neo4jDriver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, database=database)
        graphiti = Graphiti(graph_driver=driver)
        await graphiti.build_indices_and_constraints()
    except Exception as exc:  # noqa: BLE001 - the graph is optional; a bad connection must not stop the app
        logger.warning("Knowledge graph disabled: could not open %s: %s", settings.neo4j_uri, exc)
        if graphiti is not None:
            await graphiti.close()
        return None
    client = graphiti
    logger.info("Knowledge graph ready: neo4j=%s database=%s", settings.neo4j_uri, database)
    return graphiti


async def _home_database(settings: Settings) -> str:
    """Aura names its database after the instance, not 'neo4j', so ask the server which one is home."""
    from neo4j import AsyncGraphDatabase

    async with AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    ) as neo4j_driver:
        records, _, _ = await neo4j_driver.execute_query("CALL db.info() YIELD name RETURN name", database_=None)
    return records[0]["name"]


async def close_graph() -> None:
    global client
    if client is not None:
        await client.close()
        client = None
