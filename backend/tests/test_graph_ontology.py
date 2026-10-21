import os
from types import SimpleNamespace

import pytest

_env = dict(os.environ)
from graphiti_core.edges import EntityEdge  # noqa: E402
from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types  # noqa: E402

# graphiti_core calls load_dotenv() on import; without this the repo's .env leaks into every later test.
os.environ.clear()
os.environ.update(_env)

from app.integrations import graph_ontology as onto  # noqa: E402
from app.repositories import graph_catalog, graph_search  # noqa: E402


def test_entity_types_pass_graphitis_own_check():
    assert validate_entity_types(onto.ENTITY_TYPES)


def test_edge_attributes_do_not_shadow_edge_fields():
    for name, model in onto.EDGE_TYPES.items():
        assert not set(model.model_fields) & set(EntityEdge.model_fields), name


def test_edge_type_map_names_only_known_types():
    for (source, target), names in onto.EDGE_TYPE_MAP.items():
        assert source in onto.ENTITY_TYPES and target in onto.ENTITY_TYPES
        assert set(names) <= set(onto.EDGE_TYPES)


def test_every_extraction_excludes_the_untyped_default():
    kwargs = onto.extraction_kwargs({"Theme": ["Education", "Health"]})
    assert kwargs["excluded_entity_types"] == ["Entity"]
    assert "Education, Health" in kwargs["custom_extraction_instructions"]


@pytest.mark.parametrize(
    ("name", "source", "target", "allowed"),
    [
        ("FUNDS", ["Entity", "Funder"], ["Entity", "Organization"], True),
        ("FUNDS", ["Organization"], ["Funder"], False),
        ("WORKS_IN", ["Organization"], ["Location"], True),
        ("MENTIONED_IN", ["Organization"], ["Location"], False),
        ("LOCATED_IN", ["Location"], ["Location"], True),
        ("FUNDS", ["Entity"], ["Organization"], False),
        ("FUNDS", ["GovernmentBody"], ["Organization"], True),
        ("PARTNERS_WITH", ["Organization"], ["Funder"], True),
        ("PARTNERS_WITH", ["Funder"], ["Funder"], True),
        ("PARTNERS_WITH", ["Organization"], ["GovernmentBody"], True),
        ("FUNDS", ["Organization"], ["Organization"], True),
        ("IMPLEMENTS", ["Program"], ["Scheme"], True),
        ("RUNS", ["GovernmentBody"], ["Scheme"], True),
        ("SERVES", ["Organization"], ["PopulationGroup"], True),
        ("SERVES", ["Organization"], ["Theme"], False),
    ],
)
def test_edge_allowed(name, source, target, allowed):
    assert onto.edge_allowed(name, source, target) is allowed


ROWS = {
    "orgs": [{"id": 1, "name": "Pratham", "legal_form": "trust"}],
    "funders": [{"id": 2, "name": "Tata Trusts", "funder_type": "foundation"}],
    "locations": [
        {"id": 10, "name": "Assam", "kind": "state", "parent_id": None},
        {"id": 11, "name": "Kamrup", "kind": "district", "parent_id": 10},
    ],
    "programs": [{"id": 5, "name": "Read India", "status": "active", "org_id": 1, "funder_id": None}],
    "tags": [
        {"id": 7, "label": "Education", "kind": "domain", "parent_id": None},
        {"id": 8, "label": "Foundational literacy", "kind": "sub_theme", "parent_id": 7},
    ],
    "org_locations": [{"org_id": 1, "location_id": 11, "role": "operates"}],
    "funder_locations": [{"funder_id": 2, "location_id": 99, "role": "priority"}],
    "org_tags": [{"org_id": 1, "tag_id": 7}],
    "funder_tags": [],
    "program_tags": [],
    "partner_lines": [
        {"id": 3, "funder_id": 2, "partner_org_id": 1, "amount": 500000, "fiscal_year": "FY2023-24",
         "project_name": None}
    ],
}


def test_build_catalog_types_every_row_and_skips_edges_to_missing_rows():
    nodes, edges = graph_catalog.build_catalog(ROWS)
    assert {n["sangam_id"]: n["label"] for n in nodes} == {
        "org:1": "Organization", "funder:2": "Funder", "location:10": "Location", "location:11": "Location",
        "program:5": "Program", "tag:7": "Theme", "tag:8": "Theme",
    }
    names = {(e["name"], e["source"], e["target"]) for e in edges}
    assert names == {
        ("LOCATED_IN", "location:11", "location:10"),
        ("WORKS_IN", "org:1", "location:11"),
        ("FOCUSES_ON", "org:1", "tag:7"),
        ("RUNS", "org:1", "program:5"),
        ("FUNDS", "funder:2", "org:1"),
        ("PART_OF", "tag:8", "tag:7"),
    }
    funds = next(e for e in edges if e["name"] == "FUNDS")
    assert funds["attributes"] == {"amount_inr": 500000.0, "fiscal_year": "FY2023-24", "activity_id": 3}


def test_catalog_edges_fit_the_ontology():
    nodes, edges = graph_catalog.build_catalog(ROWS)
    label = {n["sangam_id"]: n["label"] for n in nodes}
    for e in edges:
        assert onto.edge_allowed(e["name"], [label[e["source"]]], [label[e["target"]]]), e


def test_node_uuids_are_fixed_per_group():
    assert graph_catalog.node_uuid("sangam", "org:1") == graph_catalog.node_uuid("sangam", "org:1")
    assert graph_catalog.node_uuid("sangam", "org:1") != graph_catalog.node_uuid("trial", "org:1")


class FakeDriver:
    def __init__(self):
        self.queries = []

    async def execute_query(self, query, **params):
        self.queries.append((query, params))
        return [{"uuid": "x", "labels": ["Entity", "Location"]}], None, None


def _node(uuid, name, *labels):
    return SimpleNamespace(uuid=uuid, name=name, labels=["Entity", *labels], attributes={})


def _edge(uuid, name, source, target):
    return SimpleNamespace(uuid=uuid, name=name, fact=f"{name} fact", source_node_uuid=source, target_node_uuid=target)


async def test_extract_deletes_off_ontology_facts_and_reports_types(monkeypatch):
    nodes = [_node("f", "Tata Trusts", "Funder"), _node("o", "Pratham", "Organization")]
    edges = [
        _edge("e1", "FUNDS", "f", "o"),
        _edge("e2", "MENTIONS", "o", "f"),
        _edge("e3", "WORKS_IN", "o", "x"),
        _edge("e1", "FUNDS", "f", "o"),
    ]
    calls = {}

    async def add_episode(**kwargs):
        calls["kwargs"] = kwargs
        return SimpleNamespace(nodes=nodes, edges=edges)

    deleted = []

    async def delete_by_uuids(driver, uuids):
        deleted.extend(uuids)

    async def link_nodes(client, pool, found):
        return {"o": "org:1"}

    async def reconcile_closed(client, *, group_id, nodes, linked):
        return ["Skill stuff (Theme)"]

    monkeypatch.setattr(EntityEdge, "delete_by_uuids", staticmethod(delete_by_uuids))
    monkeypatch.setattr(graph_search, "link_nodes", link_nodes)
    monkeypatch.setattr(graph_search, "reconcile_closed", reconcile_closed)
    client = SimpleNamespace(add_episode=add_episode, driver=FakeDriver())

    result = await graph_search.extract(client, None, name="n", text="t", source_description="d",
                                        group_id="sangam", vocab={"Theme": ["Education"]})

    assert calls["kwargs"]["excluded_entity_types"] == ["Entity"]
    assert deleted == ["e2"]
    assert result["facts"] == ["FUNDS fact", "WORKS_IN fact"]
    assert result["dropped_facts"] == ["MENTIONS: MENTIONS fact"]
    assert result["unmapped"] == ["Skill stuff (Theme)"]
    assert result["entities"] == [
        {"name": "Tata Trusts", "type": "Funder", "sangam_id": None},
        {"name": "Pratham", "type": "Organization", "sangam_id": "org:1"},
    ]


def test_themes_fold_into_their_taxonomy_node_and_the_rest_are_unmapped():
    keep = graph_catalog.node_uuid("sangam", "tag:7")
    nodes = [
        _node(keep, "Education", "Theme"),
        _node("dup", "education", "Theme"),
        _node("odd", "Skill stuff", "Theme"),
        _node("away", "Health", "Theme"),
        _node("o", "Pratham", "Organization"),
    ]
    linked = {keep: "tag:7", "dup": "tag:7", "away": "tag:99", "o": "org:1"}
    merges, unmapped = graph_catalog.plan_closed("sangam", nodes, linked, {keep})
    assert merges == {"dup": keep}
    assert [n.name for n in unmapped] == ["Skill stuff"]


async def test_reconcile_merges_then_labels_unmapped():
    keep = graph_catalog.node_uuid("sangam", "tag:7")

    class Driver(FakeDriver):
        async def execute_query(self, query, **params):
            self.queries.append((query, params))
            return [{"uuid": keep}], None, None

    client = SimpleNamespace(driver=Driver())
    nodes = [_node("dup", "education", "Theme"), _node("odd", "Skill stuff", "Theme")]
    unmapped = await graph_catalog.reconcile_closed(client, group_id="sangam", nodes=nodes, linked={"dup": "tag:7"})
    assert unmapped == ["Skill stuff (Theme)"]
    merge, label = client.driver.queries[1:]
    assert "DETACH DELETE dup" in merge[0] and merge[1] == {"dup": "dup", "keep": keep}
    assert "SET n:Unmapped" in label[0] and label[1] == {"uuids": ["odd"]}


def test_extraction_lists_each_taxonomy_as_the_only_choices():
    text = onto.instructions({"Theme": ["Education", "Foundational literacy"], "Scheme": ["DAY-NRLM", "PMKVY"],
                              "PopulationGroup": ["Women", "Tribal communities"]})
    assert "Education, Foundational literacy" in text
    assert "DAY-NRLM, PMKVY" in text and "Women, Tribal communities" in text
    assert "{" not in text


def test_an_unseeded_taxonomy_falls_back_to_an_open_list():
    text = onto.instructions({})
    assert onto.OPEN_LIST["Scheme"] in text and onto.OPEN_LIST["PopulationGroup"] in text


def test_closed_types_fold_schemes_and_groups_too():
    keep = graph_catalog.node_uuid("sangam", "tag:30")
    nodes = [_node("dup", "NRLM", "Scheme"), _node("odd", "farmers", "PopulationGroup"),
             _node("g", "Assam State Rural Livelihood Mission", "GovernmentBody")]
    merges, unmapped = graph_catalog.plan_closed("sangam", nodes, {"dup": "tag:30"}, {keep})
    assert merges == {"dup": keep}
    assert [n.name for n in unmapped] == ["farmers"]


def test_catalog_types_tags_by_kind_and_names_the_edge_after_it():
    rows = {**ROWS,
            "tags": [{"id": 7, "label": "Education", "kind": "domain", "parent_id": None},
                     {"id": 30, "label": "DAY-NRLM", "kind": "scheme", "parent_id": None},
                     {"id": 40, "label": "Women", "kind": "population", "parent_id": None},
                     {"id": 50, "label": "SDG 4", "kind": "sdg", "parent_id": None}],
            "org_tags": [{"org_id": 1, "tag_id": t} for t in (7, 30, 40, 50)]}
    nodes, edges = graph_catalog.build_catalog(rows)
    labels = {n["sangam_id"]: n["label"] for n in nodes}
    assert labels["tag:30"] == "Scheme" and labels["tag:40"] == "PopulationGroup" and "tag:50" not in labels
    assert {(e["name"], e["target"]) for e in edges if e["source"] == "org:1" and e["target"].startswith("tag:")} == {
        ("FOCUSES_ON", "tag:7"), ("IMPLEMENTS", "tag:30"), ("SERVES", "tag:40")}
    for e in edges:
        assert onto.edge_allowed(e["name"], [labels[e["source"]]], [labels[e["target"]]]), e


async def test_search_graph_tool_types_each_end_and_cites_catalog_rows(monkeypatch):
    from datetime import UTC, datetime

    from app.agent.tools import graph_tools

    seen = {}

    async def search(client, **kwargs):
        seen.update(kwargs)
        return [{"uuid": "abcdef1234", "fact": "Tata Trusts funds Pratham", "name": "FUNDS",
                 "valid_at": datetime(2024, 4, 1, tzinfo=UTC), "invalid_at": None,
                 "source": {"name": "Tata Trusts", "type": "Funder", "sangam_id": "funder:2"},
                 "target": {"name": "Pratham", "type": "Organization", "sangam_id": None}}]

    monkeypatch.setattr(graph_tools.graphiti, "client", object())
    monkeypatch.setattr(graph_tools.graph_search, "search", search)
    out = await graph_tools.search_graph.ainvoke({"query": "who funds Pratham", "types": ["Funder"]})
    assert seen["types"] == ["Funder"]
    assert out == ("[graph:abcdef12] Tata Trusts funds Pratham (valid from 01 Apr 2024, still current)"
                   " — Tata Trusts (Funder) [funder:2] -FUNDS-> Pratham (Organization)")
