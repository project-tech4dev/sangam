"""Seed the taxonomy: Schedule VII, then the theme tree and the vocabularies it points at.

`db/migrations/0002_taxonomy.sql` widened `tags.kind` to allow `'csr_sector'`
and its header promised `python -m seed.taxonomy_seed`. The module never
existed, so nothing ever pointed `funder_csr_spend.csr_sector_id` at anything
and every promoted spend row left it NULL.

Schedule VII is a closed statutory list, which is exactly what makes it safe to
normalise against. A funder's own words for a theme stay on the row; this is
only the shelf they are filed under.

The theme taxonomy (`themes.json`, `common.json`) lands in the same table: one
`tags` row per domain, theme, sub-theme, lens, SDG, scheme and population group,
`parent_id` for the domain -> theme -> sub_theme tree, and one `tag_links` row
per cross-reference (sub-theme -> SDG / clause / scheme, lens -> SDG).

Idempotent: run it as often as you like.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass

import psycopg

TAXONOMY = pathlib.Path(__file__).parent / "data" / "taxonomy"
DATA = TAXONOMY / "schedule_vii.json"

# Every kind this module owns. A row of one of these kinds that the files no longer
# name is deprecated, never deleted: org_tags may still point at it.
OWNED_KINDS = ("domain", "theme", "sub_theme", "lens", "sdg", "scheme", "population")


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def seed_schedule_vii(cur) -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rows = payload["categories"]
    for order, category in enumerate(rows):
        cur.execute(
            """
            INSERT INTO tags (slug, label, kind, code, description, sort_order, status)
            VALUES (%s, %s, 'csr_sector', %s, %s, %s, 'active')
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                kind = EXCLUDED.kind,
                code = EXCLUDED.code,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order
            """,
            (
                f"csr-{category['slug']}",
                category["label"],
                category["code"],
                f"Schedule VII clause ({category['code']}). {payload['source_url']}",
                order,
            ),
        )
    return len(rows)


@dataclass(frozen=True)
class Tag:
    slug: str
    label: str
    kind: str
    code: str
    sort_order: int
    parent: str | None = None
    """The parent's slug; resolved to parent_id at write time."""
    domain: str | None = None
    description: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class Link:
    tag: str
    linked: str
    """A slug, or `clause:<code>` for a Schedule VII row, which is keyed by code."""
    note: str | None = None


def taxonomy_rows(themes: dict, common: dict) -> tuple[list[Tag], list[Link]]:
    """The tags and links the two files describe, parents before children. Pure."""
    tags: list[Tag] = []
    links: list[Link] = []

    sdgs = {code for code, _ in common["sdgs"]}
    for i, (code, label) in enumerate(common["sdgs"]):
        tags.append(Tag(f"sdg-{code}", label, "sdg", code, i))
    for i, (code, label) in enumerate(common["population"]):
        tags.append(Tag(f"population-{code}", label, "population", code, i))

    schemes: dict[str, str] = {}
    for d in themes["domains"]:
        for t in d["themes"]:
            for s in t["sub_themes"]:
                for name in s["schemes"]:
                    schemes.setdefault(slugify(name), name)
    for i, (code, label) in enumerate(schemes.items()):
        tags.append(Tag(f"scheme-{code}", label, "scheme", code, i))

    def sdg(code: str, owner: str) -> str:
        if code not in sdgs:
            raise ValueError(f"{owner} names SDG {code!r}, which common.json does not list")
        return f"sdg-{code}"

    for i, lens in enumerate(themes["lenses"]):
        slug = f"lens-{lens['code']}"
        tags.append(Tag(slug, lens["label"], "lens", lens["code"], i))
        links += [Link(slug, sdg(code, slug)) for code in lens["adds_sdgs"]]

    for di, d in enumerate(themes["domains"]):
        dslug = f"domain-{d['domain']}"
        status = d["status"]
        tags.append(Tag(dslug, d["label"], "domain", d["domain"], di, None, d["domain"], d["source"], status))
        for ti, t in enumerate(d["themes"]):
            tslug = f"theme-{t['code']}"
            tags.append(Tag(tslug, t["label"], "theme", t["code"], ti, dslug, d["domain"], None, status))
            for si, s in enumerate(t["sub_themes"]):
                sslug = f"sub_theme-{s['code']}"
                tags.append(Tag(sslug, s["label"], "sub_theme", s["code"], si, tslug, d["domain"], None, status))
                links += [Link(sslug, sdg(code, sslug)) for code in dict.fromkeys(s["sdgs"])]
                # Several MCA sectors can sit under one clause; one link per clause, sectors in the note.
                by_clause: dict[str, list[str]] = {}
                for ref in s["csr"]:
                    by_clause.setdefault(ref["clause"], []).append(ref["sector"])
                links += [Link(sslug, f"clause:{c}", "; ".join(sectors)) for c, sectors in by_clause.items()]
                links += [Link(sslug, f"scheme-{slugify(name)}") for name in dict.fromkeys(s["schemes"])]

    slugs = [t.slug for t in tags]
    if len(slugs) != len(set(slugs)):
        dupes = sorted({s for s in slugs if slugs.count(s) > 1})
        raise ValueError(f"taxonomy slugs collide: {', '.join(dupes)}")
    return tags, links


def seed_taxonomy(cur) -> dict[str, int]:
    """Write the theme taxonomy. Needs seed_schedule_vii first: sub-themes link to its clauses."""
    themes = json.loads((TAXONOMY / "themes.json").read_text(encoding="utf-8"))
    common = json.loads((TAXONOMY / "common.json").read_text(encoding="utf-8"))
    tags, links = taxonomy_rows(themes, common)

    ids: dict[str, int] = {}
    for t in tags:
        cur.execute(
            """
            INSERT INTO tags (slug, label, kind, code, parent_id, domain, description, status, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                kind = EXCLUDED.kind,
                code = EXCLUDED.code,
                parent_id = EXCLUDED.parent_id,
                domain = EXCLUDED.domain,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                sort_order = EXCLUDED.sort_order
            RETURNING id
            """,
            (t.slug, t.label, t.kind, t.code, ids[t.parent] if t.parent else None,
             t.domain, t.description, t.status, t.sort_order),
        )
        ids[t.slug] = cur.fetchone()[0]

    cur.execute(
        "UPDATE tags SET status = 'deprecated' WHERE kind = ANY(%s) AND NOT slug = ANY(%s)",
        (list(OWNED_KINDS), list(ids)),
    )

    cur.execute("SELECT code, id FROM tags WHERE kind = 'csr_sector'")
    clauses = {f"clause:{code}": id_ for code, id_ in cur.fetchall()}

    # Replace, rather than merge, the links of every tag this seed owns, so a dropped reference goes too.
    cur.execute("DELETE FROM tag_links WHERE tag_id = ANY(%s)", (list(ids.values()),))
    for link in links:
        target = clauses.get(link.linked) if link.linked.startswith("clause:") else ids.get(link.linked)
        if target is None:
            raise ValueError(f"{link.tag} links to {link.linked}, which is not a tag")
        cur.execute(
            "INSERT INTO tag_links (tag_id, linked_tag_id, note) VALUES (%s, %s, %s)",
            (ids[link.tag], target, link.note),
        )

    counts: dict[str, int] = {}
    for t in tags:
        counts[t.kind] = counts.get(t.kind, 0) + 1
    counts["links"] = len(links)
    return counts


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        count = seed_schedule_vii(cur)
        counts = seed_taxonomy(cur)
        conn.commit()
    print(f"seeded: {count} Schedule VII categories as tags(kind='csr_sector')")
    print("seeded: " + ", ".join(f"{n} {kind}" for kind, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
