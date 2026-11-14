"""Reads and writes on the Graphiti knowledge graph in Neo4j."""

from __future__ import annotations

from datetime import UTC, datetime


async def search(client, *, query: str, group_id: str | None, limit: int) -> list[dict]:
    edges = await client.search(query=query, num_results=limit, group_ids=[group_id] if group_id else None)
    return [{"uuid": e.uuid, "fact": e.fact, "valid_at": e.valid_at, "invalid_at": e.invalid_at} for e in edges]


async def add_episode(client, *, text: str, name: str, source_description: str, group_id: str | None) -> dict:
    from graphiti_core.nodes import EpisodeType

    result = await client.add_episode(
        name=name,
        episode_body=text,
        source=EpisodeType.text,
        source_description=source_description,
        reference_time=datetime.now(UTC),
        group_id=group_id,
    )
    return {"entities": [n.name for n in result.nodes], "facts": [e.fact for e in result.edges]}


async def clear(client, *, group_id: str | None) -> int:
    from graphiti_core.utils.maintenance.graph_data_operations import clear_data

    where = "WHERE n.group_id = $group_id" if group_id else ""
    records, _, _ = await client.driver.execute_query(
        f"MATCH (n) {where} RETURN count(n) AS n", group_id=group_id)
    await clear_data(client.driver, group_ids=[group_id] if group_id else None)
    return records[0]["n"]
