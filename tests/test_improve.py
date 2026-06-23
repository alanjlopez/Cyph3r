from cyph3r.improve import Findings, analyze, merge_duplicates_cypher
from tests.fakes import FakeGraph


def test_analyze_surfaces_orphans_and_duplicates():
    graph = FakeGraph(
        responses=[
            (
                "WHERE NOT (n)--()",
                [{"labels": ["Person"], "props": {"name": "Zoe"}, "id": 7}],
            ),
            (
                "size(ids) > 1",
                [{"labels": ["Person"], "name": "Alice", "ids": [1, 2]}],
            ),
        ]
    )

    findings = analyze(graph, meta_prefix="Cyph3r")

    assert len(findings.orphans) == 1
    assert findings.orphans[0]["props"]["name"] == "Zoe"
    assert len(findings.duplicates) == 1
    assert findings.duplicates[0]["name"] == "Alice"
    assert not findings.is_empty()


def test_analyze_excludes_meta_namespace_via_prefix_param():
    graph = FakeGraph()  # no canned rows -> empty findings
    analyze(graph, meta_prefix="Cyph3r")
    # Both scans must filter the meta namespace by passing the prefix param.
    for query, params in graph.reads:
        assert params.get("prefix") == "Cyph3r"
        assert "STARTS WITH $prefix" in query


def test_empty_findings():
    assert Findings().is_empty()
    assert "No structural issues" in Findings().summary()


def test_merge_duplicates_cypher_uses_apoc():
    cypher = merge_duplicates_cypher()
    assert "apoc.refactor.mergeNodes" in cypher
    assert "$ids" in cypher
