"""Replay recorded Ask questions through Jev and compare with what the model did (docs/features/2026-11-24-jev-ask-decisions.md).

    make jev-replay                                  # production, every Ask turn
    make jev-replay JEV_ENV=staging SINCE=2026-11-01 OUT=/tmp/jev.jsonl

Runs in the local backend container with its Langfuse and TypeSafe keys. Prints agreement, latency and cost.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime

from langfuse import get_client

from app.ask.agent import SKILLS_DIR
from app.ask.audit import DATA_TOOLS
from app.ask.jev import NO_SKILL, Did, questions, route_agrees, skill_agrees, skill_catalog
from app.core.config import get_settings
from app.integrations.typesafe import decide

SKILL_PREFIX = "/skills/"


def pages(api, **kw):
    cursor = None
    while True:
        page = api.observations.get_many(limit=100, cursor=cursor, **kw)
        yield from page.data
        cursor = getattr(page.meta, "cursor", None)
        if not cursor:
            return


def _field(obs, name):
    return obs.get(name) if isinstance(obs, dict) else getattr(obs, name, None)


def _args(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def label(api, trace_id: str, environment: str) -> Did:
    """What the recorded turn did, from its tool observations."""
    tools = sorted(pages(api, trace_id=trace_id, type="TOOL", environment=environment, fields="core,basic,io"),
                   key=lambda o: str(_field(o, "startTime") or _field(o, "start_time")))
    skills, used = [], False
    for tool in tools:
        name = _field(tool, "name")
        path = str(_args(_field(tool, "input")).get("file_path", ""))
        if name == "read_file" and path.startswith(SKILL_PREFIX) and path.endswith("/SKILL.md"):
            skill = path.removeprefix(SKILL_PREFIX).split("/", 1)[0]
            if skill not in skills:
                skills.append(skill)
        used = used or name in DATA_TOOLS
    return Did(tuple(skills), used)


def turns(api, environment: str, since: datetime) -> list[dict]:
    """Each typed Ask question, oldest first, with the question before it in the same chat."""
    roots = pages(api, name="sangam_ask", is_root_observation=True, environment=environment,
                  from_start_time=since, fields="core,basic,io")
    rows = sorted(
        ({"trace": _field(r, "traceId") or _field(r, "trace_id"), "session": _field(r, "sessionId") or "",
          "at": str(_field(r, "startTime") or _field(r, "start_time")), "question": _field(r, "input")} for r in roots),
        key=lambda r: r["at"],
    )
    last: dict[str, str] = {}
    out = []
    for row in rows:
        question = row["question"]
        if not isinstance(question, str) or not question.strip():
            continue  # a resume or a button answer, not a typed question
        row["previous"] = last.get(row["session"])
        last[row["session"]] = question
        out.append(row)
    return out


def _pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100)[int(q * 100) - 1] if len(values) > 1 else (values[0] if values else 0)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="production")
    parser.add_argument("--since", default="2026-10-01")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.typesafe_api_key:
        print("TYPESAFE_API_KEY is not set in the backend's environment.")
        return 1
    api = get_client().api
    asking = questions(skill_catalog(SKILLS_DIR))
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    cases = turns(api, args.env, since)
    if args.limit:
        cases = cases[-args.limit:]
    print(f"{len(cases)} typed Ask questions in {args.env} since {args.since}")

    results, failed = [], 0
    for case in cases:
        did = label(api, case["trace"], args.env)
        decision = decide({"question": case["question"][:1000], "previous_question": case["previous"]},
                          asking, name="jev_replay", settings=settings, trace=False)
        if decision is None:
            failed += 1
            continue
        route, route_p, _ = decision.choice("route")
        skill, skill_p, _ = decision.choice("skill")
        results.append({
            "trace": case["trace"], "question": case["question"][:120],
            "route": route, "route_p": round(route_p, 3), "used_data": did.used_data,
            "route_agree": route_agrees(route, did) if route else None,
            "skill": skill, "skill_p": round(skill_p, 3), "model_skill": did.skills[0] if did.skills else NO_SKILL,
            "skill_agree": skill_agrees(skill, did) if skill else None,
            "latency_ms": decision.latency_ms, "tokens": decision.input_tokens,
            "estimated": decision.estimated, "cost_usd": decision.cost_usd,
        })

    if args.out:
        with open(args.out, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in results)
    report(results, failed)
    return 0


def report(results: list[dict], failed: int) -> None:
    if not results:
        print(f"No decisions ({failed} calls failed).")
        return
    n = len(results)
    latency = [r["latency_ms"] for r in results]
    print(f"\n{n} decided, {failed} failed")
    for key in ("route", "skill"):
        agreed = [r for r in results if r[f"{key}_agree"] is not None]
        hits = sum(r[f"{key}_agree"] for r in agreed)
        print(f"{key}: agrees {hits}/{len(agreed)} ({hits / max(len(agreed), 1):.0%})")
        for threshold in (0.5, 0.7, 0.8, 0.9):
            sure = [r for r in agreed if r[f"{key}_p"] >= threshold]
            ok = sum(r[f"{key}_agree"] for r in sure)
            print(f"  at p>={threshold}: {len(sure)} decided, {ok} agree ({ok / max(len(sure), 1):.0%})")
    print("route picks:", dict(Counter(r["route"] for r in results)))
    print("skill (jev, model):", dict(Counter((r["skill"], r["model_skill"]) for r in results)))
    print(f"latency ms: p50 {_pct(latency, 0.5):.0f}, p90 {_pct(latency, 0.9):.0f}, max {max(latency)}")
    tokens = sum(r["tokens"] for r in results)
    cost = sum(r["cost_usd"] for r in results)
    estimated = sum(r["estimated"] for r in results)
    print(f"tokens: {tokens} ({tokens / n:.0f} a call{', some estimated' if estimated else ''}); "
          f"cost ${cost:.5f} (${cost / n:.6f} a call)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
