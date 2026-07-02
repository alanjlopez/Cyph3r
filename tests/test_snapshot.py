from cyph3r.snapshot import graph_snapshot
from tests.fakes import FakeGraph


def _graph_with_data():
    return FakeGraph(
        responses=[
            (
                "RETURN elementId(n) AS id",
                [
                    {"id": "n1", "labels": ["Person"], "props": {"name": "Alice"}},
                    {"id": "n2", "labels": ["Person"], "props": {"name": "Bob"}},
                ],
            ),
            (
                "elementId(a) IN $ids",
                [
                    {
                        "id": "e1",
                        "source": "n1",
                        "target": "n2",
                        "type": "KNOWS",
                        "props": {},
                    }
                ],
            ),
            ("count(n) AS total", [{"total": 2}]),
        ]
    )


def test_snapshot_maps_nodes_and_edges():
    snap = graph_snapshot(_graph_with_data(), meta_prefix="Cyph3r")

    assert [n["id"] for n in snap["nodes"]] == ["n1", "n2"]
    assert snap["nodes"][0]["properties"]["name"] == "Alice"
    assert len(snap["edges"]) == 1
    assert snap["edges"][0]["type"] == "KNOWS"
    assert snap["counts"]["nodes_shown"] == 2
    assert snap["truncated"] is False


def test_snapshot_excludes_meta_namespace_by_default():
    graph = _graph_with_data()
    graph_snapshot(graph, meta_prefix="Cyph3r")

    node_query, node_params = graph.reads[0]
    assert "STARTS WITH $prefix" in node_query
    assert node_params.get("prefix") == "Cyph3r"


def test_snapshot_edges_scoped_to_returned_node_ids():
    graph = _graph_with_data()
    graph_snapshot(graph, meta_prefix="Cyph3r")

    edge_query, edge_params = graph.reads[1]
    assert "elementId(a) IN $ids" in edge_query
    assert edge_params["ids"] == ["n1", "n2"]


def test_snapshot_truncated_when_total_exceeds_shown():
    graph = FakeGraph(
        responses=[
            ("RETURN elementId(n) AS id", [{"id": "n1", "labels": ["Person"], "props": {}}]),
            ("count(n) AS total", [{"total": 50}]),
        ]
    )
    snap = graph_snapshot(graph, node_limit=1)
    assert snap["truncated"] is True
    assert snap["counts"]["nodes_total"] == 50


def test_snapshot_include_meta_drops_prefix_filter():
    graph = FakeGraph(
        responses=[
            ("RETURN elementId(n) AS id", []),
            ("count(n) AS total", [{"total": 0}]),
        ]
    )
    graph_snapshot(graph, include_meta=True)
    node_query = graph.reads[0][0]
    assert "STARTS WITH" not in node_query
