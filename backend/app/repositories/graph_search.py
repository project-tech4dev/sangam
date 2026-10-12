"""Reads and writes on the Graphiti knowledge graph in Neo4j."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.integrations import storage

TEXT_TYPES = (".md", ".txt", ".csv", ".json", ".html", ".htm")
CHUNK_CHARS = 8_000  # Graphiti extracts per episode; a whole report in one prompt loses facts


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


def document_text(key: str, data: bytes) -> str | None:
    """The file's text, or None for a type not read yet (.xlsx, images)."""
    from app.agent.tools.files import extract_pdf_text

    suffix = Path(key).suffix.lower()
    if suffix == ".pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(data)
            handle.flush()
            text, _ = extract_pdf_text(Path(handle.name))
        return text
    if suffix in TEXT_TYPES:
        return data.decode("utf-8", errors="replace")
    return None


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    text = text.strip()
    return [text[i:i + size] for i in range(0, len(text), size)]


async def _episode_exists(client, name: str, group_id: str) -> bool:
    records, _, _ = await client.driver.execute_query(
        "MATCH (e:Episodic {name: $name, group_id: $group_id}) RETURN count(e) AS n",
        name=name, group_id=group_id)
    return records[0]["n"] > 0


async def add_document(client, *, bucket: str, key: str, group_id: str) -> dict:
    """One Storage file into the graph, a chunk per episode; chunks already added are skipped."""
    from graphiti_core.nodes import EpisodeType

    result = {"key": key, "status": "added", "chunks": 0, "entities": 0, "facts": 0, "reason": None}
    data = await storage.download(bucket, key)
    if data is None:
        return {**result, "status": "failed", "reason": "could not download"}
    text = await asyncio.to_thread(document_text, key, data)
    if text is None:
        return {**result, "status": "skipped", "reason": f"{Path(key).suffix or 'no extension'} is not read yet"}
    parts = chunks(text)
    if not parts:
        return {**result, "status": "skipped", "reason": "no text layer (likely scanned)"}
    for index, part in enumerate(parts, start=1):
        name = f"{bucket}/{key}#{index}"
        if await _episode_exists(client, name, group_id):
            continue
        episode = await client.add_episode(
            name=name,
            episode_body=part,
            source=EpisodeType.text,
            source_description=f"supabase storage {bucket}/{key} (part {index} of {len(parts)})",
            reference_time=datetime.now(UTC),
            group_id=group_id,
        )
        result["chunks"] += 1
        result["entities"] += len(episode.nodes)
        result["facts"] += len(episode.edges)
    if result["chunks"] == 0:
        return {**result, "status": "skipped", "reason": "already in the graph"}
    return result


async def add_documents(client, *, bucket: str, prefix: str, limit: int, group_id: str) -> dict:
    files = await storage.list_all(bucket, prefix)
    results = []
    for f in files[:limit]:
        try:
            results.append(await add_document(client, bucket=bucket, key=f["key"], group_id=group_id))
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the rest of the batch
            results.append({"key": f["key"], "status": "failed", "chunks": 0, "entities": 0, "facts": 0,
                            "reason": f"{type(exc).__name__}: {exc}"})
    return {"bucket": bucket, "prefix": prefix, "group_id": group_id, "found": len(files), "files": results}
