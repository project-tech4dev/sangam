"""Render docs/ from the research table. Runs on the HOST, never in the container.

The backend image mounts only app/, seed/ and db/, so a process inside it cannot
write a repo file — and should not: these are reviewed artifacts. This reads the
database and writes markdown, the way `make evals` runs pytest on the host venv.
The rendering itself is in `brief.py` and runs anywhere; only the writing is
host-only. `save_research` publishes the same bytes to the bucket as it saves.

Two kinds of file:
  docs/entities/<slug>.md          one per researched organisation, fully generated
  docs/clients/<ngo>/README.md     hand-written analysis, with generated blocks
                                   between <!-- generated:x --> markers

Text outside a marker is never touched, because a generator cannot write the
reading that makes a client file worth having.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.ingest.brief import entity_markdown, publish_markdown

REPO = Path(__file__).resolve().parents[3]
ENTITIES = REPO / "docs" / "entities"
CLIENTS = REPO / "docs" / "clients"


def marker(name: str) -> tuple[str, str]:
    return f"<!-- generated:{name} -->", "<!-- /generated -->"


def replace_block(text: str, name: str, body: str) -> str:
    """Swap what is between one pair of markers, leaving everything else alone."""
    start, end = marker(name)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    block = f"{start}\n{body.rstrip()}\n{end}"
    if pattern.search(text):
        return pattern.sub(lambda _: block, text)
    return text.rstrip() + "\n\n" + block + "\n"


def client_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No organisation has been researched for this client yet._"
    lines = ["| Organisation | Researched | Status | Facts | Detail |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['canonical_name'] or r['entity_name']} | {r['researched_on']} | "
            f"{r['status']} | {r['fact_count']} | "
            f"[entity file](../../entities/{r['slug']}.md) |"
        )
    return "\n".join(lines)


async def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    async with await psycopg.AsyncConnection.connect(url, row_factory=dict_row) as conn:
        # The newest row per slug: re-researching an entity supersedes, it does
        # not append a second file.
        rows = await (
            await conn.execute(
                "SELECT DISTINCT ON (slug) * FROM entity_research "
                "ORDER BY slug, researched_at DESC"
            )
        ).fetchall()
        # Names for the index, when the catalog happens to know them.
        named = {
            r["slug"]: r["name"]
            for r in await (await conn.execute("SELECT slug, name FROM orgs")).fetchall()
        }

    # Which clients exist is decided by the repo, not the catalog: a client file
    # is hand-written and committed, and an empty database must not make it
    # disappear from the index.
    clients = [
        {"slug": d.name, "name": named.get(d.name, d.name.replace("-", " ").title())}
        for d in sorted(CLIENTS.iterdir())
        if d.is_dir() and (d / "README.md").exists()
    ]

    ENTITIES.mkdir(parents=True, exist_ok=True)
    published = 0
    for row in rows:
        markdown = entity_markdown(row)
        (ENTITIES / f"{row['slug']}.md").write_text(markdown, encoding="utf-8")
        # The same file in the bucket, so the app can link to a brief without
        # reading the repo. git stays the place it is reviewed; this is the
        # copy the product serves. A no-op when Storage is not configured.
        if await publish_markdown(row["slug"], markdown):
            published += 1
    print(f"docs/entities: {len(rows)} file(s)" + (f", {published} published" if published else ""))

    # Every researched funder is shown to every client for now: which funders
    # matter to which NGO is a matching question, and matching is not built.
    funders = [r for r in rows if r["entity_kind"] != "org"]
    written = 0
    for client in clients:
        readme = CLIENTS / client["slug"] / "README.md"
        if not readme.exists():
            continue
        text = readme.read_text(encoding="utf-8")
        readme.write_text(replace_block(text, "funders", client_block(funders)), encoding="utf-8")
        written += 1
    print(f"docs/clients: refreshed {written} client file(s)")

    index = ["| Client | Status |", "|---|---|"]
    for client in clients:
        if (CLIENTS / client["slug"] / "README.md").exists():
            index.append(f"| [{client['name']}]({client['slug']}/README.md) | "
                         f"{len(funders)} funders researched |")
    idx = CLIENTS / "README.md"
    if idx.exists() and len(index) > 2:
        idx.write_text(replace_block(idx.read_text(encoding="utf-8"), "index", "\n".join(index)),
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
