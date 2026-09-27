"""Load the Sangam taxonomy into `tags` (needs migrations 0001 and 0004). Idempotent.

    python -m seed.taxonomy_seed

Reads seed/data/taxonomy/:
    common.json          SDGs, formal sector labels, population groups, NGO Darpan map
    <domain>.json        one tree per domain: livelihoods.json (active), health.json and
                         education.json (draft until reviewed)
    _template.json       starting point for a new domain (files starting with '_' are skipped)

Slugs: sdg-8, sector-health, pop-women, domain-livelihoods, livelihoods-01-a, livelihoods-01-a-informal.
Each domain file lists its sources; each node's "refs" name the source ids and the standard
codes behind it (SDG targets, OECD CRS purpose codes, ISCED levels, NIC 2008 divisions,
Indian government programmes). Both are kept in tags.meta so any cell can be traced.
Cells missing from a domain file are marked 'deprecated', never deleted. A node's
'replaces' list sets replaced_by on the old slugs so existing tag links keep resolving.

derive_tags() expands a cell plus conditions into the SDG and sector tags it implies,
for use by extraction scripts and the agent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg

DATA = Path(__file__).parent / "data"
TAX_DIR = Path(os.environ.get("TAXONOMY_DIR", DATA / "taxonomy"))


def _upsert(cur, slug, label, kind, *, domain=None, code=None, level=None, parent_id=None,
            description=None, meta=None, status="active", sort_order=None) -> int:
    cur.execute(
        """
        INSERT INTO tags (slug, label, kind, domain, code, level, parent_id, description, meta, status, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (slug) DO UPDATE SET
          label = EXCLUDED.label, kind = EXCLUDED.kind, domain = EXCLUDED.domain, code = EXCLUDED.code,
          level = EXCLUDED.level, parent_id = EXCLUDED.parent_id, description = EXCLUDED.description,
          meta = EXCLUDED.meta, status = EXCLUDED.status, sort_order = EXCLUDED.sort_order,
          replaced_by = NULL
        RETURNING id
        """,
        (slug, label, kind, domain, code, level, parent_id, description, json.dumps(meta or {}), status, sort_order),
    )
    return cur.fetchone()[0]


def _darpan_labels() -> set[str]:
    labels: set[str] = set()
    for path in (DATA / "darpan").glob("*.json"):
        working = (json.loads(path.read_text()).get("sections", {}) or {}).get("working_sectors", {}) or {}
        for key in ("primary_sectors", "secondary_sectors"):
            labels.update(p.strip() for p in str(working.get(key) or "").split(",") if p.strip())
    return labels


def seed_common(cur) -> dict[str, int]:
    common = json.loads((TAX_DIR / "common.json").read_text())
    counts = {"sdg": 0, "sector": 0, "population": 0, "darpan_sector": 0, "theme": 0}
    for i, (num, name) in enumerate(common["sdgs"]):
        _upsert(cur, f"sdg-{num}", f"SDG {num}: {name}", "sdg", code=f"SDG {num}", level="goal", sort_order=i)
        counts["sdg"] += 1
    for i, (slug, label) in enumerate(common["sectors"]):
        _upsert(cur, f"sector-{slug}", label, "sector", level="label", sort_order=i)
        counts["sector"] += 1
    for i, (slug, label) in enumerate(common["population"]):
        _upsert(cur, f"pop-{slug}", label, "population", level="group", sort_order=i)
        counts["population"] += 1
    # Tags that seed.py created as 'sector' are Darpan labels or free-text research labels.
    darpan = _darpan_labels()
    cur.execute("SELECT id, label FROM tags WHERE kind = 'sector' AND slug NOT LIKE 'sector-%%'")
    for tag_id, label in cur.fetchall():
        if label in darpan:
            cur.execute("UPDATE tags SET kind = 'darpan_sector', meta = %s WHERE id = %s",
                        (json.dumps({"maps_to": common["darpan_map"].get(label, [])}), tag_id))
            counts["darpan_sector"] += 1
        else:
            cur.execute("UPDATE tags SET kind = 'theme' WHERE id = %s", (tag_id,))
            counts["theme"] += 1
    return counts


def seed_domain(cur, spec: dict) -> int:
    d = spec["domain"]
    status = "draft" if spec.get("status") == "draft" else "active"
    levels = spec.get("levels", [])
    variants = spec.get("variants") or None
    seen: set[str] = set()
    replaces: list[tuple[str, str]] = []

    root_slug = f"domain-{d}"
    root_id = _upsert(cur, root_slug, spec["label"], "domain", domain=d, level="domain", status=status, meta={
        "version": spec.get("version"), "tree_name": spec.get("tree_name"), "source": spec.get("source"),
        "levels": levels, "modifiers": spec.get("modifiers", []), "enabler_kinds": spec.get("enabler_kinds", []),
        "variants": variants["items"] if variants else [],
        "sources": spec.get("sources", []),        # full source list, so every ref can be traced
    })
    seen.add(root_slug)

    def walk(nodes, parent_id, path, depth):
        for i, node in enumerate(nodes):
            node_path = path + [node["code"]]
            slug = f"{d}-" + "-".join(p.lower() for p in node_path)
            level = levels[depth] if depth < len(levels) else "node"
            meta = {
                "sdgs": [f"sdg-{n}" for n in node.get("sdgs", [])],
                "sectors": [f"sector-{s}" for s in node.get("sectors", [])],
                "adds": {k: [f"sdg-{n}" for n in v] for k, v in (node.get("adds") or {}).items()},
            }
            if node.get("refs"):  # standard codes and source ids behind this node
                meta["refs"] = node["refs"]
            node_id = _upsert(cur, slug, node["label"], "cell", domain=d, code=".".join(node_path), level=level,
                              parent_id=parent_id, description=node.get("note") or None, meta=meta,
                              status=status, sort_order=i)
            seen.add(slug)
            replaces.extend((old, slug) for old in node.get("replaces", []))
            if variants:  # old-slug-<variant> is replaced by new-slug-<variant>
                replaces.extend((f"{old}-{v['code']}", f"{slug}-{v['code']}")
                                for old in node.get("replaces", []) for v in variants["items"])
            if variants and variants.get("apply_to_level") == level:
                for j, v in enumerate(variants["items"]):
                    _upsert(cur, f"{slug}-{v['code']}", f"{node['label']} ({v['label']})", "cell", domain=d,
                            code=f"{'.'.join(node_path)}.{v['code']}", level=variants["level"],
                            parent_id=node_id, meta={"variant": v["code"]}, status=status, sort_order=j)
                    seen.add(f"{slug}-{v['code']}")
            walk(node.get("children", []), node_id, node_path, depth + 1)

    walk(spec.get("nodes", []), root_id, [], 0)

    for old, new in replaces:
        cur.execute("UPDATE tags SET status = 'deprecated', replaced_by = (SELECT id FROM tags WHERE slug = %s) "
                    "WHERE slug = %s", (new, old))
    cur.execute("UPDATE tags SET status = 'deprecated' WHERE domain = %s AND kind IN ('domain', 'cell') "
                "AND status <> 'deprecated' AND NOT (slug = ANY(%s))", (d, list(seen)))
    return len(seen)


def seed_taxonomy(cur) -> dict[str, int]:
    counts = seed_common(cur)
    loaded: list[str] = []
    for path in sorted(TAX_DIR.glob("*.json")):
        if path.name.startswith("_") or path.name == "common.json":
            continue
        spec = json.loads(path.read_text())
        counts[f"domain:{spec['domain']}"] = seed_domain(cur, spec)
        loaded.append(spec["domain"])
    # A domain whose file was removed is deprecated, never deleted.
    cur.execute("UPDATE tags SET status = 'deprecated' WHERE kind IN ('domain', 'cell') "
                "AND status <> 'deprecated' AND NOT (domain = ANY(%s))", (loaded,))
    return counts


def derive_tags(cur, cell_slug: str, conditions: tuple[str, ...] = ()) -> list[str]:
    """Tags implied by a cell: its domain, plus SDGs and sectors from the cell and its
    ancestors, plus 'adds' whose key matches the cell's variant or a given condition.
    derive_tags(cur, 'livelihoods-01-a-informal', ('climate_smart',))
      -> domain-livelihoods, sdg-1, sdg-2, sdg-8, sdg-10, sdg-13, sector-agriculture-livelihoods
    """
    cur.execute(
        """
        WITH RECURSIVE up AS (
          SELECT id, parent_id, kind, slug, meta FROM tags WHERE slug = %s
          UNION ALL
          SELECT t.id, t.parent_id, t.kind, t.slug, t.meta FROM tags t JOIN up ON t.id = up.parent_id
        ) SELECT kind, slug, meta FROM up
        """,
        (cell_slug,),
    )
    rows = cur.fetchall()
    if not rows:
        return []
    keys = set(conditions) | {m.get("variant") for _, _, m in rows if m.get("variant")}
    out: set[str] = set()
    for kind, slug, meta in rows:
        if kind == "domain":
            out.add(slug)
        out.update(meta.get("sdgs", []))
        out.update(meta.get("sectors", []))
        for key, extra in (meta.get("adds") or {}).items():
            if key in keys:
                out.update(extra)
    return sorted(out)


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        counts = seed_taxonomy(cur)
    print("taxonomy seeded:", ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
