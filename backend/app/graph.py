"""Graphiti temporal knowledge graph over FalkorDB.

The graph stores relationship facts EXTRACTED from source text (episodes) —
Postgres remains the system of record, and the graph is rebuildable from it
(see seed/graph_seed.py). Graph features are optional: they activate only when
FALKORDB_HOST is set and an OpenAI key is available (Graphiti's default
extraction LLM, embedder, and reranker are all OpenAI; Anthropic offers no
embedding models).
"""

from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger(__name__)

# Set by the lifespan (like app.db.pool); None means graph features are off.
graphiti = None


def graph_status(settings: Settings) -> str:
    if settings.graph_backend == "neo4j":
        if not settings.neo4j_uri:
            return "NEO4J_URI is not set"
    elif not settings.falkordb_host:
        return "FALKORDB_HOST is not set"
    if not settings.openai_api_key:
        return "OPENAI_API_KEY is not set (Graphiti needs it for embeddings/extraction)"
    return "ok"


async def open_graph(settings: Settings):
    """Initialise the Graphiti client, or return None with a logged reason."""
    global graphiti
    status = graph_status(settings)
    if status != "ok":
        logger.warning("Knowledge graph disabled: %s", status)
        return None
    # Imported lazily so the app still boots if graph deps are missing.
    from graphiti_core import Graphiti

    if settings.graph_backend == "neo4j":
        client = Graphiti(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        backend_desc = f"neo4j={settings.neo4j_uri}"
    else:
        from graphiti_core.driver.falkordb_driver import FalkorDriver

        driver = FalkorDriver(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            database="sangam",
        )
        client = Graphiti(graph_driver=driver)
        backend_desc = f"falkordb={settings.falkordb_host}:{settings.falkordb_port}"
    await client.build_indices_and_constraints()
    graphiti = client
    logger.info("Knowledge graph ready: %s", backend_desc)
    return client


async def close_graph() -> None:
    global graphiti
    if graphiti is not None:
        await graphiti.close()
        graphiti = None
