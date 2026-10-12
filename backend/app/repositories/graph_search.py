"""Reads and writes on the Graphiti knowledge graph in Neo4j."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.integrations import storage

TEXT_TYPES = (".md", ".txt", ".csv", ".json", ".html", ".htm")
CHUNK_CHARS = 8_000  # Graphiti extracts per episode; a whole report in one prompt loses facts
_in_flight: set[asyncio.Task] = set()  # asyncio holds tasks weakly; a shielded chunk must outlive a stop


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


async def groups(client) -> list[dict]:
    records, _, _ = await client.driver.execute_query("""
        MATCH (n) WHERE n.group_id IS NOT NULL
        RETURN n.group_id AS group_id, count(n) AS nodes, count(CASE WHEN n:Episodic THEN 1 END) AS episodes
        ORDER BY group_id""")
    return [dict(r) for r in records]


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


async def document_events(client, *, bucket: str, key: str, size: int | None, group_id: str):
    """One Storage file into the graph, a chunk per episode, yielding a progress event at each step."""
    from graphiti_core.nodes import EpisodeType

    result = {"key": key, "status": "added", "chunks": 0, "entities": 0, "facts": 0, "reason": None, "parts": []}
    yield {"event": "downloading", "key": key, "bytes": size}
    data = await storage.download(bucket, key)
    if data is None:
        yield {"event": "file_done", "file": {**result, "status": "failed", "reason": "could not download"}}
        return
    yield {"event": "extracting", "key": key, "bytes": len(data), "type": Path(key).suffix.lower() or None}
    text = await asyncio.to_thread(document_text, key, data)
    if text is None:
        reason = f"{Path(key).suffix or 'no extension'} is not read yet"
        yield {"event": "file_done", "file": {**result, "status": "skipped", "reason": reason}}
        return
    parts = chunks(text)
    yield {"event": "chunked", "key": key, "chars": len(text.strip()), "chunks": len(parts), "chunk_chars": CHUNK_CHARS}
    if not parts:
        yield {"event": "file_done", "file": {**result, "status": "skipped", "reason": "no text layer (likely scanned)"}}
        return
    for index, part in enumerate(parts, start=1):
        name = f"{bucket}/{key}#{index}"
        if await _episode_exists(client, name, group_id):
            chunk = {"index": index, "chars": len(part), "status": "skipped", "entities": [], "facts": []}
            result["parts"].append(chunk)
            yield {"event": "chunk_done", "key": key, "total": len(parts), "episode": name, "chunk": chunk}
            continue
        yield {"event": "chunk_start", "key": key, "index": index, "total": len(parts), "chars": len(part),
               "episode": name, "group_id": group_id, "preview": part[:200]}
        # Stopping cancels this generator; a chunk Graphiti has started still lands whole, never half-written.
        task = asyncio.ensure_future(client.add_episode(
            name=name,
            episode_body=part,
            source=EpisodeType.text,
            source_description=f"supabase storage {bucket}/{key} (part {index} of {len(parts)})",
            reference_time=datetime.now(UTC),
            group_id=group_id,
        ))
        _in_flight.add(task)
        task.add_done_callback(_in_flight.discard)
        episode = await asyncio.shield(task)
        chunk = {"index": index, "chars": len(part), "status": "added",
                 "entities": [n.name for n in episode.nodes], "facts": [e.fact for e in episode.edges]}
        result["chunks"] += 1
        result["entities"] += len(chunk["entities"])
        result["facts"] += len(chunk["facts"])
        result["parts"].append(chunk)
        yield {"event": "chunk_done", "key": key, "total": len(parts), "episode": name, "chunk": chunk}
    if result["chunks"] == 0:
        result = {**result, "status": "skipped", "reason": "already in the graph"}
    yield {"event": "file_done", "file": result}


async def documents_events(client, *, bucket: str, prefix: str, limit: int, group_id: str):
    yield {"event": "listing", "bucket": bucket, "prefix": prefix}
    files = await storage.list_all(bucket, prefix)
    picked = files[:limit]
    yield {"event": "listed", "bucket": bucket, "prefix": prefix, "group_id": group_id, "found": len(files),
           "reading": [f["key"] for f in picked]}
    for number, f in enumerate(picked, start=1):
        yield {"event": "file_start", "key": f["key"], "number": number, "total": len(picked)}
        try:
            async for event in document_events(client, bucket=bucket, key=f["key"], size=f.get("size"),
                                               group_id=group_id):
                yield event
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the rest of the batch
            yield {"event": "file_done", "file": {"key": f["key"], "status": "failed", "chunks": 0, "entities": 0,
                                                  "facts": 0, "reason": f"{type(exc).__name__}: {exc}", "parts": []}}
    yield {"event": "done"}


async def add_documents(client, *, bucket: str, prefix: str, limit: int, group_id: str) -> dict:
    found, results = 0, []
    async for event in documents_events(client, bucket=bucket, prefix=prefix, limit=limit, group_id=group_id):
        if event["event"] == "listed":
            found = event["found"]
        elif event["event"] == "file_done":
            results.append(event["file"])
    return {"bucket": bucket, "prefix": prefix, "group_id": group_id, "found": found, "files": results}
