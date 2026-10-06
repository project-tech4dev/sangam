"""`python -m app.matching`: load and activate criteria, and run a match from the shell."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.matching import registry, service
from app.matching.config import DEFAULT_PATH, CriteriaError, load_yaml
from app.matching.models import Ambiguous, Assessment
from app.matching.themes import backfill_programme_themes


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.matching")
    sub = p.add_subparsers(dest="cmd", required=True)
    load = sub.add_parser("load", help="validate the criteria file and store it as a draft")
    load.add_argument("--file", default=str(DEFAULT_PATH))
    act = sub.add_parser("activate", help="make one loaded version the live one")
    act.add_argument("--version", type=int, required=True)
    act.add_argument("--by")
    sub.add_parser("sets", help="list loaded versions and their status")
    match = sub.add_parser("match", help="shortlist funders for an org")
    match.add_argument("--org", required=True)
    match.add_argument("--criteria", default=registry.ACTIVE, help="'active' or a version number")
    match.add_argument("--limit", type=int, default=20)
    explain = sub.add_parser("explain", help="every check for an org against one or more funders")
    explain.add_argument("--org", required=True)
    explain.add_argument("--funder", action="append", required=True)
    explain.add_argument("--criteria", default=registry.ACTIVE)
    sub.add_parser("backfill-programme-themes", help="tag untagged programmes with a Schedule VII clause")
    return p


def _git_sha() -> str | None:
    """`make criteria-load` passes GIT_SHA in, since the container has no checkout."""
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _ref(value: str) -> str | int:
    return value if value == registry.ACTIVE else int(value)


async def _one(conn: Any, kind: str, text: str) -> int | None:
    got = await service.resolve(conn, kind, text)
    if isinstance(got, Ambiguous):
        names = ", ".join(f"{c.name} ({c.slug})" for c in got.candidates) or "nothing close"
        print(f"{kind} {text!r} is ambiguous: {names}", file=sys.stderr)
        return None
    return got.id


def _score(a: Assessment) -> str:
    return f"{a.score_min}-{a.score_max} (coverage {a.coverage})"


def _print_shortlist(sl) -> None:
    print(f"{sl.org.name} [org:{sl.org.id}] · criteria v{sl.criteria_version} ({sl.criteria_hash[:8]}) · "
          f"{sl.total_funders} funders: {len(sl.ranked)} shown, {len(sl.not_enough_recorded)} not enough "
          f"recorded, {len(sl.did_not_pass)} did not pass")
    for i, a in enumerate(sl.ranked, start=sl.offset + 1):
        gaps = ", ".join(f"{g.code}:{g.outcome}" for g in a.gaps[:4])
        print(f"{i:>3}. {a.funder.name} [funder:{a.funder.id}] {a.gate_status} {_score(a)}  gaps: {gaps or '-'}")
    if sl.not_enough_recorded:
        print("not enough recorded: " + ", ".join(f.name for f in sl.not_enough_recorded))
    for a in sl.did_not_pass:
        print(f"did not pass: {a.funder.name} [funder:{a.funder.id}] on {', '.join(a.failed_gates)}")


def _print_assessment(a: Assessment) -> None:
    print(f"\n{a.funder.name} [funder:{a.funder.id}] · criteria v{a.criteria_version} · {a.gate_status} "
          f"{_score(a)}")
    for c in a.checks:
        level = f" ({c.level})" if c.level else ""
        print(f"  {c.code:<12} {c.role:<9} {c.outcome:<8}{level} {c.basis:<18} {c.reason_code} "
              f"{c.reason_params or ''}")


async def run(argv: list[str], conn: Any) -> int:
    """Runs one command on `conn` and never commits; `main` does that."""
    args = _parser().parse_args(argv)
    if args.cmd == "load":
        _, raw = load_yaml(args.file)
        version = await registry.load_draft(conn, raw, git_sha=_git_sha())
        print(f"{raw['set']} v{version} loaded as draft; activate with: make criteria-activate VERSION={version}")
    elif args.cmd == "activate":
        await registry.activate(conn, registry.SET_NAME, args.version, by=args.by)
        print(f"{registry.SET_NAME} v{args.version} is now active")
    elif args.cmd == "sets":
        for r in await registry.list_sets(conn):
            print(f"v{r['version']:<4} {r['status']:<8} {r['content_hash'][:8]} git {r['git_sha'] or '-'} "
                  f"activated {r['activated_at'] or '-'}")
    elif args.cmd == "match":
        org_id = await _one(conn, "org", args.org)
        if org_id is None:
            return 1
        _print_shortlist(await service.shortlist(conn, org_id, criteria=_ref(args.criteria), limit=args.limit))
    elif args.cmd == "explain":
        org_id = await _one(conn, "org", args.org)
        funder_ids = [await _one(conn, "funder", f) for f in args.funder]
        if org_id is None or None in funder_ids:
            return 1
        for a in await service.assess_many(conn, org_id, funder_ids, criteria=_ref(args.criteria)):
            _print_assessment(a)
    elif args.cmd == "backfill-programme-themes":
        print(f"{await backfill_programme_themes(conn)} programme tags written")
    return 0


async def _main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    async with await psycopg.AsyncConnection.connect(url, row_factory=dict_row, autocommit=False) as conn:
        try:
            code = await run(argv, conn)
        except (CriteriaError, LookupError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if code == 0:
            await conn.commit()
        return code


def main() -> int:
    return asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
