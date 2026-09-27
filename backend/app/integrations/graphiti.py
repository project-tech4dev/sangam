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

    graphiti = Graphiti(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    await graphiti.build_indices_and_constraints()
    client = graphiti
    logger.info("Knowledge graph ready: neo4j=%s", settings.neo4j_uri)
    return graphiti


async def close_graph() -> None:
    global client
    if client is not None:
        await client.close()
        client = None
