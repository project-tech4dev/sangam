"""Sangam's catalog in the knowledge graph: Postgres rows written as typed nodes, and names linked back to them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.integrations.graph_ontology import CLOSED_TYPES, entity_type

NAMESPACE = uuid.UUID("6f1c2a52-8d3e-4b7a-9a1e-5c0d2f7b9e41")
LINK_SIMILARITY = 0.6  # pg_trgm similarity below this is a different name, not a spelling of the same one

LOCATION_IDS = """
    WITH RECURSIVE used AS (
      SELECT location_id AS id FROM org_locations
      UNION SELECT location_id FROM funder_locations
      UNION SELECT registered_location_id FROM orgs WHERE registered_location_id IS NOT NULL
      UNION SELECT location_id FROM funder_activity WHERE location_id IS NOT NULL
      UNION SELECT state_location_id FROM funder_activity WHERE state_location_id IS NOT NULL
    ), tree AS (
      SELECT l.id, l.parent_id FROM locations l JOIN used u ON u.id = l.id
      UNION SELECT p.id, p.parent_id FROM locations p JOIN tree t ON p.id = t.parent_id
    )
    SELECT DISTINCT id FROM tree"""

THEME_KINDS = ("domain", "theme", "sub_theme")
# Each graph type a tag kind becomes; the first list per type is the taxonomy, the second the fallback.
TAG_TYPES: dict[str, list[list[str]]] = {
    "Theme": [list(THEME_KINDS), ["sector"]],
    "Scheme": [["scheme"]],
    "PopulationGroup": [["population"]],
}
TAG_TYPE = {"sector": "Theme", "darpan_sector": "Theme", "scheme": "Scheme", "population": "PopulationGroup",
            **{kind: "Theme" for kind in THEME_KINDS}}
CATALOG_KINDS = [*THEME_KINDS, "scheme", "population"]
VOCABULARY = """
    SELECT label FROM tags WHERE status = 'active' AND kind = ANY(%s) ORDER BY sort_order NULLS LAST, label"""


def _tag_where(graph_type: str) -> str:
    kinds = ", ".join(f"'{k}'" for k, t in TAG_TYPE.items() if t == graph_type)
    return f"status = 'active' AND kind IN ({kinds})"


# The rows a typed entity may name, in the order tried, as (citation prefix, table, extra filter).
LINK_TABLES: dict[str, list[tuple[str, str, str]]] = {
    "Organization": [("org", "orgs", ""), ("funder", "funders", "")],
    "Funder": [("funder", "funders", ""), ("org", "orgs", "")],
    "GovernmentBody": [("funder", "funders", ""), ("org", "orgs", "")],
    "Location": [("location", "locations", "")],
    "Program": [("program", "programs", "")],
    **{t: [("tag", "tags", _tag_where(t))] for t in CLOSED_TYPES},
}
NAME_COLUMN = {"orgs": "name", "funders": "name", "locations": "name", "programs": "name", "tags": "label"}
HAS_ALIASES = {"orgs", "funders", "locations"}
TAG_EDGE = {"Theme": ("FOCUSES_ON", "works on"), "Scheme": ("IMPLEMENTS", "implements"),
            "PopulationGroup": ("SERVES", "serves")}


async def _rows(conn: Any, sql: str, params: Any = None) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def vocabulary(pool) -> dict[str, list[str]]:
    """The labels each closed type may take: the taxonomy if it is seeded, else Darpan's sectors for themes."""
    found: dict[str, list[str]] = {}
    async with pool.connection() as conn:
        for graph_type, choices in TAG_TYPES.items():
            for kinds in choices:
                found[graph_type] = [r["label"] for r in await _rows(conn, VOCABULARY, (kinds,))]
                if found[graph_type]:
                    break
    return found


async def read_catalog(pool) -> dict[str, list[dict]]:
    async with pool.connection() as conn:
        location_ids = [r["id"] for r in await _rows(conn, LOCATION_IDS)]
        return {
            "orgs": await _rows(conn, "SELECT id, name, legal_form FROM orgs ORDER BY id"),
            "funders": await _rows(conn, "SELECT id, name, funder_type FROM funders ORDER BY id"),
            "locations": await _rows(
                conn, "SELECT id, name, kind, parent_id FROM locations WHERE id = ANY(%s) ORDER BY id",
                (location_ids,)),
            "programs": await _rows(conn, "SELECT id, name, status, org_id, funder_id FROM programs ORDER BY id"),
            "tags": await _rows(conn, """
                SELECT t.id, t.label, t.kind, t.parent_id FROM tags t
                WHERE t.id IN (SELECT tag_id FROM org_tags UNION SELECT tag_id FROM funder_tags
                               UNION SELECT tag_id FROM program_tags)
                   OR (t.status = 'active' AND t.kind = ANY(%s))
                ORDER BY t.id""", (CATALOG_KINDS,)),
            "org_locations": await _rows(conn, "SELECT org_id, location_id, role FROM org_locations"),
            "funder_locations": await _rows(conn, "SELECT funder_id, location_id, role FROM funder_locations"),
            "org_tags": await _rows(conn, "SELECT org_id, tag_id FROM org_tags"),
            "funder_tags": await _rows(conn, "SELECT funder_id, tag_id FROM funder_tags"),
            "program_tags": await _rows(conn, "SELECT program_id, tag_id FROM program_tags"),
            "partner_lines": await _rows(conn, """
                SELECT id, funder_id, partner_org_id, amount, fiscal_year, project_name FROM funder_activity
                WHERE kind = 'partner' AND partner_org_id IS NOT NULL ORDER BY id"""),
        }


def node_uuid(group_id: str, sangam_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{group_id}/{sangam_id}"))


def build_catalog(rows: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    """Plain node and edge dicts from catalog rows; pure, so the shape is testable without Neo4j."""
    nodes: dict[str, dict] = {}

    def node(sangam_id: str, name: str, label: str, **attributes: Any) -> None:
        nodes[sangam_id] = {"sangam_id": sangam_id, "name": name, "label": label,
                            "attributes": {k: v for k, v in attributes.items() if v is not None}}

    for o in rows["orgs"]:
        node(f"org:{o['id']}", o["name"], "Organization", org_kind=o["legal_form"])
    for f in rows["funders"]:
        node(f"funder:{f['id']}", f["name"], "Funder", funder_kind=f["funder_type"])
    places = {loc["id"]: loc for loc in rows["locations"]}
    for loc in rows["locations"]:
        node(f"location:{loc['id']}", loc["name"], "Location", level=loc["kind"])
    for p in rows["programs"]:
        node(f"program:{p['id']}", p["name"], "Program", status=p["status"])
    for t in rows["tags"]:
        if graph_type := TAG_TYPE.get(t.get("kind") or "sector"):
            node(f"tag:{t['id']}", t["label"], graph_type, level=t.get("kind"))

    edges: list[dict] = []

    def edge(name: str, source: str, target: str, fact: str, **attributes: Any) -> None:
        if source in nodes and target in nodes:
            edges.append({"name": name, "source": source, "target": target, "fact": fact,
                          "attributes": {k: v for k, v in attributes.items() if v is not None}})

    def named(sangam_id: str) -> str:
        return nodes[sangam_id]["name"] if sangam_id in nodes else ""

    for loc in rows["locations"]:
        if loc["parent_id"] in places:
            child, parent = f"location:{loc['id']}", f"location:{loc['parent_id']}"
            edge("LOCATED_IN", child, parent, f"{named(child)} is in {named(parent)}")
    for t in rows["tags"]:
        child, parent = f"tag:{t['id']}", f"tag:{t.get('parent_id')}"
        edge("PART_OF", child, parent, f"{named(child)} is part of {named(parent)}")
    for r in rows["org_locations"]:
        o, loc = f"org:{r['org_id']}", f"location:{r['location_id']}"
        verb = "is registered in" if r["role"] == "registered" else "works in"
        edge("WORKS_IN", o, loc, f"{named(o)} {verb} {named(loc)}", role=r["role"])
    for r in rows["funder_locations"]:
        f, loc = f"funder:{r['funder_id']}", f"location:{r['location_id']}"
        edge("WORKS_IN", f, loc, f"{named(f)} funds work in {named(loc)}", role=r["role"])
    def tagged(source: str, tag_id: int) -> None:
        target = f"tag:{tag_id}"
        if target in nodes:
            name, verb = TAG_EDGE[nodes[target]["label"]]
            edge(name, source, target, f"{named(source)} {verb} {named(target)}")

    for r in rows["org_tags"]:
        tagged(f"org:{r['org_id']}", r["tag_id"])
    for r in rows["funder_tags"]:
        tagged(f"funder:{r['funder_id']}", r["tag_id"])
    for r in rows["program_tags"]:
        tagged(f"program:{r['program_id']}", r["tag_id"])
    for p in rows["programs"]:
        owner = f"org:{p['org_id']}" if p["org_id"] else f"funder:{p['funder_id']}"
        edge("RUNS", owner, f"program:{p['id']}", f"{named(owner)} runs {p['name']}")
    for line in rows["partner_lines"]:
        f, o = f"funder:{line['funder_id']}", f"org:{line['partner_org_id']}"
        project = f" for {line['project_name']}" if line["project_name"] else ""
        edge("FUNDS", f, o, f"{named(f)} funds {named(o)}{project} ({line['fiscal_year']})",
             amount_inr=float(line["amount"]) if line["amount"] is not None else None,
             fiscal_year=line["fiscal_year"], activity_id=line["id"])
    return list(nodes.values()), edges


async def sync_catalog(client, pool, *, group_id: str) -> dict:
    """Write the catalog into one group with fixed uuids: new rows are added, changed ones updated, and catalog
    nodes or edges whose row is gone are deleted. Nodes keep the summaries documents gave them."""
    from graphiti_core.edges import EntityEdge, create_entity_edge_embeddings
    from graphiti_core.nodes import EntityNode, create_entity_node_embeddings

    nodes, edges = build_catalog(await read_catalog(pool))
    uuids = {n["sangam_id"]: node_uuid(group_id, n["sangam_id"]) for n in nodes}
    existing_nodes = {n.uuid: n for n in await EntityNode.get_by_uuids(client.driver, list(uuids.values()))}

    to_save: list = []
    for n in nodes:
        old = existing_nodes.get(uuids[n["sangam_id"]])
        entity = EntityNode(
            uuid=uuids[n["sangam_id"]], name=n["name"], group_id=group_id, labels=[n["label"]],
            summary=old.summary if old else "",
            attributes={**(old.attributes if old else {}), **n["attributes"],
                        "sangam_id": n["sangam_id"], "from_catalog": True},
            name_embedding=old.name_embedding if old and old.name == n["name"] else None,
        )
        to_save.append(entity)
    await create_entity_node_embeddings(client.embedder, [e for e in to_save if e.name_embedding is None])
    for entity in to_save:
        await entity.save(client.driver)

    now = datetime.now(UTC)
    edge_uuids = {str(uuid.uuid5(NAMESPACE, f"{group_id}/{e['name']}/{e['source']}/{e['target']}")): e for e in edges}
    existing_edges = {e.uuid: e for e in await EntityEdge.get_by_uuids(client.driver, list(edge_uuids))}
    edge_objs: list = []
    for edge_id, e in edge_uuids.items():
        old = existing_edges.get(edge_id)
        edge_objs.append(EntityEdge(
            uuid=edge_id, group_id=group_id, name=e["name"], fact=e["fact"],
            source_node_uuid=uuids[e["source"]], target_node_uuid=uuids[e["target"]],
            created_at=old.created_at if old else now, valid_at=old.valid_at if old else None,
            episodes=old.episodes if old else [],
            fact_embedding=old.fact_embedding if old and old.fact == e["fact"] else None,
            attributes={**e["attributes"], "from_catalog": True},
        ))
    await create_entity_edge_embeddings(client.embedder, [e for e in edge_objs if e.fact_embedding is None])
    for edge_obj in edge_objs:
        await edge_obj.save(client.driver)

    removed, _, _ = await client.driver.execute_query(
        """
        CALL {
          MATCH ()-[e:RELATES_TO {group_id: $group_id, from_catalog: true}]->() WHERE NOT e.uuid IN $edges
          DELETE e RETURN count(*) AS n
        }
        CALL {
          MATCH (n:Entity {group_id: $group_id, from_catalog: true}) WHERE NOT n.uuid IN $nodes
          DETACH DELETE n RETURN count(*) AS m
        }
        RETURN n AS edges, m AS nodes""",
        group_id=group_id, edges=list(edge_uuids), nodes=list(uuids.values()))
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["label"]] = by_type.get(n["label"], 0) + 1
    return {
        "group_id": group_id,
        "nodes": len(nodes),
        "edges": len(edges),
        "added_nodes": len(nodes) - len(existing_nodes),
        "added_edges": len(edges) - len(existing_edges),
        "removed_nodes": removed[0]["nodes"],
        "removed_edges": removed[0]["edges"],
        "by_type": by_type,
    }


async def find_sangam_id(conn: Any, label: str, name: str) -> str | None:
    """The catalog row a typed entity names: an exact name or alias first, then the closest trigram match."""
    for prefix, table, extra in LINK_TABLES.get(label, []):
        column = NAME_COLUMN[table]
        where = f"({extra}) AND " if extra else ""
        alias = " OR lower(%(name)s) = ANY(SELECT lower(a) FROM unnest(aliases) a)" if table in HAS_ALIASES else ""
        hit = await _rows(conn, f"SELECT id FROM {table} WHERE {where}(lower({column}) = lower(%(name)s){alias}) LIMIT 1",
                          {"name": name})
        if not hit:
            hit = await _rows(conn, f"""
                SELECT id FROM {table} WHERE {where}similarity({column}, %(name)s) >= %(min)s
                ORDER BY similarity({column}, %(name)s) DESC LIMIT 1""", {"name": name, "min": LINK_SIMILARITY})
        if hit:
            return f"{prefix}:{hit[0]['id']}"
    return None


async def link_nodes(client, pool, nodes: list) -> dict[str, str]:
    """Set sangam_id on typed entities that name a catalog row; returns uuid → sangam_id for every linked node."""
    linked: dict[str, str] = {}
    async with pool.connection() as conn:
        for node in nodes:
            if node.attributes.get("sangam_id"):
                linked[node.uuid] = node.attributes["sangam_id"]
                continue
            label = entity_type(node.labels)
            sangam_id = await find_sangam_id(conn, label, node.name) if label else None
            if sangam_id:
                linked[node.uuid] = sangam_id
                node.attributes["sangam_id"] = sangam_id
    to_set = [{"uuid": u, "sangam_id": s} for u, s in linked.items()]
    if to_set:
        await client.driver.execute_query(
            "UNWIND $rows AS row MATCH (n:Entity {uuid: row.uuid}) SET n.sangam_id = row.sangam_id", rows=to_set)
    return linked


def plan_closed(group_id: str, nodes: list, linked: dict[str, str], catalog: set[str]) -> tuple[dict, list]:
    """Which taxonomy-typed entities fold into their catalog node (dup uuid → catalog uuid), and which match none."""
    merges, unmapped = {}, []
    for node in nodes:
        if entity_type(node.labels) not in CLOSED_TYPES:
            continue
        sangam_id = linked.get(node.uuid)
        if not sangam_id:
            unmapped.append(node)
        elif (target := node_uuid(group_id, sangam_id)) in catalog and target != node.uuid:
            merges[node.uuid] = target
    return merges, unmapped


MERGE_NODE = """
    MATCH (dup:Entity {uuid: $dup}), (keep:Entity {uuid: $keep})
    CALL {
      WITH dup, keep
      MATCH (dup)-[r:RELATES_TO]->(m) WHERE m <> keep
      CREATE (keep)-[moved:RELATES_TO]->(m) SET moved = properties(r) DELETE r
    }
    CALL {
      WITH dup, keep
      MATCH (m)-[r:RELATES_TO]->(dup) WHERE m <> keep
      CREATE (m)-[moved:RELATES_TO]->(keep) SET moved = properties(r) DELETE r
    }
    CALL {
      WITH dup, keep
      MATCH (ep:Episodic)-[r:MENTIONS]->(dup)
      MERGE (ep)-[moved:MENTIONS]->(keep) ON CREATE SET moved = properties(r) DELETE r
    }
    DETACH DELETE dup"""


async def reconcile_closed(client, *, group_id: str, nodes: list, linked: dict[str, str]) -> list[str]:
    """Fold themes, schemes and population groups into the taxonomy's own nodes; label the rest Unmapped."""
    targets = [node_uuid(group_id, s) for s in set(linked.values()) if s.startswith("tag:")]
    records, _, _ = await client.driver.execute_query(
        "MATCH (n:Entity {group_id: $group_id}) WHERE n.uuid IN $uuids AND n.from_catalog RETURN n.uuid AS uuid",
        group_id=group_id, uuids=targets)
    merges, unmapped = plan_closed(group_id, nodes, linked, {r["uuid"] for r in records})
    for dup, keep in merges.items():
        await client.driver.execute_query(MERGE_NODE, dup=dup, keep=keep)
    if unmapped:
        await client.driver.execute_query("MATCH (n:Entity) WHERE n.uuid IN $uuids SET n:Unmapped",
                                          uuids=[n.uuid for n in unmapped])
    return [f"{n.name} ({entity_type(n.labels)})" for n in unmapped]
