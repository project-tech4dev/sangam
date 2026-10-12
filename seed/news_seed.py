"""Load the Media & Signals pulls in data/news.json, resolving each org, funder, place and tag by slug or LGD code.

Idempotent: a story whose main link is already stored is skipped. A story whose every org or funder is missing here is
skipped too, since it would show in no list; what it skipped is printed.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import psycopg
from psycopg.types.json import Jsonb

DATA = pathlib.Path(__file__).parent / "data" / "news.json"
NOTE = "loaded from seed/data/news.json"
STORY_COLS = ("headline", "headline_generated", "original_headline", "summary", "published_on", "date_source",
              "content_kind", "is_news", "scope", "topic", "feed", "topic_match", "topic_confidence", "visibility",
              "sentiment", "place_names", "main_host", "first_seen_at", "last_seen_at", "source_url", "source_name",
              "fetched_at", "content_hash", "extractor_version")
LINK_COLS = ("url", "host", "source_type", "original_title", "snippet", "published_on", "date_source", "archive_url",
             "fetched_at", "last_seen_at", "source_name", "content_hash", "extractor_version")


def _insert(conn: psycopg.Connection, table: str, row: dict, conflict: str = "") -> int | None:
    cols = list(row)
    got = conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) {conflict} RETURNING id",
        [row[c] for c in cols],
    ).fetchone()
    return got[0] if got else None


def load(conn: psycopg.Connection, data: dict) -> dict[str, int | set[str]]:
    orgs = dict(conn.execute("SELECT slug, id FROM orgs").fetchall())
    funders = dict(conn.execute("SELECT slug, id FROM funders").fetchall())
    tags = dict(conn.execute("SELECT slug, id FROM tags").fetchall())
    places = {(k, n, c or ""): i for i, k, n, c in conn.execute("SELECT id, kind, name, lgd_code FROM locations")}
    missing: set[str] = set()

    def who(ref: dict) -> dict | None:
        if "feed" in ref:
            return {"org_id": None, "funder_id": None, "feed": ref["feed"]}
        kind, slug = ("org", ref["org"]) if "org" in ref else ("funder", ref["funder"])
        found = (orgs if kind == "org" else funders).get(slug)
        if found is None:
            missing.add(f"{kind} {slug}")
            return None
        return {"org_id": found if kind == "org" else None, "funder_id": found if kind == "funder" else None,
                "feed": None}

    counts = dict.fromkeys(("runs", "stories", "links", "scores", "watch", "skipped_loaded", "skipped_orphan"), 0)
    runs: dict[int, int] = {}
    for r in data["runs"]:
        notes = f"{r['notes']} · {NOTE}"
        found = conn.execute("SELECT id FROM ingest_runs WHERE started_at = %s AND notes = %s",
                             (r["started_at"], notes)).fetchone()
        if found:
            runs[r["id"]] = found[0]
            continue
        subjects = []
        for s in r["subjects"]:
            w = who(s)
            if w:
                subjects.append(f"org:{w['org_id']}" if w["org_id"] else
                                f"funder:{w['funder_id']}" if w["funder_id"] else f"feed:{w['feed']}")
        runs[r["id"]] = _insert(conn, "ingest_runs", {
            "started_at": r["started_at"], "finished_at": r["finished_at"], "status": r["status"],
            "requested_sources": r["requested_sources"], "subjects": subjects, "notes": notes})
        counts["runs"] += 1

    by_story: dict[int, list[dict]] = {}
    for link in data["links"]:
        by_story.setdefault(link["story"], []).append(link)
    known = {u for (u,) in conn.execute("SELECT url FROM news_links WHERE url = ANY(%s)",
                                        ([lk["url"] for lk in data["links"]],))}

    def add_link(link: dict, story_id: int | None) -> int | None:
        if link["url"] in known:
            return None
        known.add(link["url"])
        counts["links"] += 1
        return _insert(conn, "news_links", {**{c: link[c] for c in LINK_COLS},
                                            "run_id": runs.get(link["run"]), "story_id": story_id})

    skipped: set[str] = set()
    for s in data["stories"]:
        if s["main_link"] in known:
            counts["skipped_loaded"] += 1
            continue
        entities = [(e, who(e)) for e in s["entities"]]
        if entities and not any(w for _, w in entities):
            counts["skipped_orphan"] += 1
            skipped.update(lk["url"] for lk in by_story.get(s["key"], []))
            continue
        story_id = _insert(conn, "news_stories", {c: s[c] for c in STORY_COLS})
        counts["stories"] += 1
        for e, w in entities:
            if w:
                conn.execute(
                    "INSERT INTO news_story_entities (story_id, org_id, funder_id, match, confidence, stance, "
                    "signal_type, visibility) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (story_id, w["org_id"], w["funder_id"], e["match"], e["confidence"], e["stance"],
                     e["signal_type"], e["visibility"]))
        for p in s["locations"]:
            place = places.get((p["kind"], p["name"], p["lgd_code"] or ""))
            if place is None:
                missing.add(f"place {p['kind']} {p['name']}")
                continue
            conn.execute("INSERT INTO news_story_locations VALUES (%s, %s) ON CONFLICT DO NOTHING", (story_id, place))
        for t in s["tags"]:
            if t not in tags:
                missing.add(f"tag {t}")
                continue
            conn.execute("INSERT INTO news_story_tags VALUES (%s, %s) ON CONFLICT DO NOTHING", (story_id, tags[t]))
        ids = {lk["url"]: add_link(lk, story_id) for lk in by_story.get(s["key"], [])}
        conn.execute("UPDATE news_stories SET main_link_id = %s WHERE id = %s", (ids.get(s["main_link"]), story_id))

    for link in by_story.get(None, []):
        if link["url"] not in skipped:
            add_link(link, None)

    link_ids = dict(conn.execute("SELECT url, id FROM news_links WHERE url = ANY(%s)",
                                 ([lk["url"] for lk in data["links"]],)).fetchall())
    for sc in data["scores"]:
        w = who(sc)
        if not w or sc["url"] in skipped or sc["url"] not in link_ids:
            continue
        got = conn.execute(
            "INSERT INTO news_link_scores (link_id, org_id, funder_id, feed, prompt_version, on_target, match, "
            "confidence, verdict, classified_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (link_ids[sc["url"]], w["org_id"], w["funder_id"], w["feed"], sc["prompt_version"], sc["on_target"],
             sc["match"], sc["confidence"], Jsonb(sc["verdict"]), sc["classified_at"])).fetchone()
        counts["scores"] += bool(got)

    for wt in data["watch"]:
        w = who(wt)
        if w:
            got = conn.execute(
                "INSERT INTO news_watch (org_id, funder_id, feed, searched_through, first_searched_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (w["org_id"], w["funder_id"], w["feed"], wt["searched_through"], wt["first_searched_at"])).fetchone()
            counts["watch"] += bool(got)
    return {**counts, "missing": missing}


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with psycopg.connect(dsn) as conn:
        result = load(conn, json.loads(DATA.read_text(encoding="utf-8")))
    missing = result.pop("missing")
    print("news:", ", ".join(f"{k} {v}" for k, v in result.items()))
    if missing:
        print("not in this database, so skipped:", ", ".join(sorted(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
