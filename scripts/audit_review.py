"""Check the answer audit against a person's labels in Langfuse (docs/features/2026-11-20-ask-answer-audit.md).

    make audit-review CMD=setup                    # score config `answer_correct` + queue "Ask answer review"
    make audit-review CMD=rerun SINCE=2026-11-19   # re-audit past local turns as `answer_audit_v2`, queue them

Runs in the local backend container, with its Langfuse keys and checkpoints. Prints counts and ids, never keys.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict

import httpx
from app.ask.agent import build_agent
from app.ask.audit import audit_turn
from app.core.config import get_settings
from app.db.checkpointer import make_pool, open_checkpointer
from langchain_core.messages import BaseMessage, HumanMessage
from langfuse import get_client

CONFIG = "answer_correct"
QUEUE = "Ask answer review"
SCORE = "answer_audit_v2"


def turns(messages: list[BaseMessage]) -> list[tuple[str, list[BaseMessage]]]:
    """Each question with the chat up to its answer, as the audit saw it when that turn ended."""
    starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    ends = starts[1:] + [len(messages)] if starts else []
    return [(messages[s].text.strip(), messages[:e]) for s, e in zip(starts, ends, strict=True)]


def match(traces: list[dict], chat: list[tuple[str, list[BaseMessage]]]) -> list[tuple[str, list[BaseMessage]]]:
    """Pair each trace (oldest first) with the next unused turn asking the same question."""
    used, pairs = set(), []
    for trace in sorted(traces, key=lambda t: t["startTime"]):
        question = str(trace.get("input") or "").strip()
        found = next((i for i, (q, _) in enumerate(chat) if i not in used and q == question), None)
        if found is not None:
            used.add(found)
            pairs.append((trace["traceId"], chat[found][1]))
    return pairs


class Langfuse:
    def __init__(self, settings):
        self.http = httpx.Client(
            base_url=settings.langfuse_host,
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            timeout=60,
        )

    def get(self, path: str, **params) -> dict:
        response = self.http.get(f"/api/public/{path}", params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict) -> dict:
        response = self.http.post(f"/api/public/{path}", json=body)
        response.raise_for_status()
        return response.json()

    def find(self, path: str, name: str) -> dict | None:
        return next((row for row in self.get(path, limit=100)["data"] if row["name"] == name), None)

    def roots(self, since: str) -> list[dict]:
        rows, cursor = [], None
        while True:
            params = {"name": "sangam_ask", "environment": "local", "fromStartTime": f"{since}T00:00:00Z",
                      "fields": "core,basic,io", "limit": 100, **({"cursor": cursor} if cursor else {})}
            page = self.get("v2/observations", **params)
            rows += page["data"]
            if not (cursor := page.get("meta", {}).get("cursor")):
                return rows


def setup(langfuse: Langfuse) -> None:
    config = langfuse.find("score-configs", CONFIG) or langfuse.post("score-configs", {
        "name": CONFIG, "dataType": "BOOLEAN",
        "description": "A person's label: is this Ask answer correct against Sangam's data?",
    })
    queue = langfuse.find("annotation-queues", QUEUE) or langfuse.post("annotation-queues", {
        "name": QUEUE, "scoreConfigIds": [config["id"]],
        "description": "Label Ask answers so Score Analytics can compare answer_audit with a person.",
    })
    print(f"score config {CONFIG}: {config['id']}\nqueue {QUEUE!r}: {queue['id']}")


async def rerun(langfuse: Langfuse, since: str) -> None:
    settings = get_settings()
    queue = langfuse.find("annotation-queues", QUEUE)
    by_chat = defaultdict(list)
    for trace in langfuse.roots(since):
        if trace.get("sessionId"):
            by_chat[trace["sessionId"]].append(trace)
    client = get_client()
    pool = make_pool(settings.database_url)
    await pool.open()
    scored = flagged = skipped = 0
    try:
        async with open_checkpointer(pool) as saver:
            graph = build_agent(settings, saver)
            for thread_id, traces in by_chat.items():
                state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                for trace_id, prefix in match(traces, turns(state.values.get("messages", []))):
                    verdict = audit_turn(prefix, settings.sql_audit_model)
                    if verdict is None:
                        skipped += 1
                        continue
                    client.create_score(
                        trace_id=trace_id, name=SCORE, value=1.0 if verdict.verdict == "ok" else 0.0,
                        score_id=f"{trace_id}-{SCORE}", environment="local", comment=verdict.caveat,
                        metadata={"check": verdict.check} if verdict.check else None,
                    )
                    if queue:
                        langfuse.post(f"annotation-queues/{queue['id']}/items",
                                      {"objectId": trace_id, "objectType": "TRACE"})
                    scored += 1
                    flagged += verdict.verdict == "warn"
    finally:
        client.flush()
        await pool.close()
    print(f"{scored} turns scored as {SCORE} ({flagged} flagged), {skipped} not auditable, "
          f"{len(by_chat)} chats" + ("" if queue else "; run setup first to queue them for labelling"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["setup", "rerun"])
    parser.add_argument("--since", default="2026-11-19")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.langfuse_enabled:
        sys.exit("Langfuse keys are not set in this environment.")
    langfuse = Langfuse(settings)
    if args.command == "setup":
        setup(langfuse)
    else:
        asyncio.run(rerun(langfuse, args.since))


if __name__ == "__main__":
    main()
