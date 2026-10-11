"""Bytes per AG-UI event type for one run, with the rawEvent copy split out.

Local only: needs a backend with DEV_AUTH=1, which accepts `Bearer dev`.

  python scripts/agui_bytes.py ask "Which organisations work in Assam?"
  python scripts/agui_bytes.py import "Research Wipro Foundation" --web
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from collections import defaultdict

TICKED = "Sources the person ticked for this Import run"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("agent", choices=["ask", "import"])
    p.add_argument("question")
    p.add_argument("--base", default="http://localhost:8010")
    p.add_argument("--web", action="store_true", help="import: tick public websites, so no sources card")
    p.add_argument("--library", action="store_true", help="import: tick Sangam's library")
    args = p.parse_args()

    path, thread = ("/agent", str(uuid.uuid4())) if args.agent == "ask" else ("/ingest", f"import-{uuid.uuid4()}")
    context = []
    if args.web or args.library:
        context.append({"description": TICKED, "value": json.dumps({"web": args.web, "library": args.library})})
    body = {
        "threadId": thread, "runId": str(uuid.uuid4()), "state": {}, "tools": [], "context": context,
        "forwardedProps": {}, "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": args.question}],
    }
    req = urllib.request.Request(
        args.base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": "Bearer dev"},
    )
    count: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    raw: dict[str, int] = defaultdict(int)
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=3600) as res:
        for line in res:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            event = json.loads(data)
            kind = event.get("type", "?")
            count[kind] += 1
            total[kind] += len(data)
            if event.get("rawEvent") is not None:
                raw[kind] += len(json.dumps(event["rawEvent"], separators=(",", ":")))
            if kind == "RUN_ERROR":
                print("RUN_ERROR:", event.get("message"), file=sys.stderr)

    print(f"thread {thread}, {time.monotonic() - started:.0f} s\n")
    print(f"{'event type':<28}{'count':>8}{'bytes':>14}{'rawEvent':>14}{'share':>8}")
    grand = sum(total.values()) or 1
    for kind in sorted(total, key=total.get, reverse=True):
        print(f"{kind:<28}{count[kind]:>8}{total[kind]:>14,}{raw[kind]:>14,}{total[kind] / grand:>8.0%}")
    print(f"{'total':<28}{sum(count.values()):>8}{grand:>14,}{sum(raw.values()):>14,}")


if __name__ == "__main__":
    main()
