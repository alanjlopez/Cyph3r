from cyph3r.memory import GraphMemory
from tests.fakes import FakeGraph


def test_record_memory_creates_node_and_about_links():
    graph = FakeGraph()
    memory = GraphMemory(graph, meta_prefix="Cyph3r")

    memory_id = memory.record_memory("Alice prefers email", about=["Alice"], kind="insight")

    assert memory_id  # a uuid was returned
    create_query, create_params = graph.writes[0]
    assert "Cyph3rInsight" in create_query
    assert create_params["content"] == "Alice prefers email"
    assert create_params["id"] == memory_id

    link_query, link_params = graph.writes[1]
    assert ":ABOUT" in link_query
    assert link_params["about"] == ["Alice"]


def test_recall_maps_rows_to_records():
    graph = FakeGraph(
        responses=[
            (
                "RETURN m.id AS id, m.kind AS kind",
                [{"id": "m1", "kind": "insight", "content": "remember this", "created_at": 1}],
            )
        ]
    )
    memory = GraphMemory(graph)

    records = memory.recall(limit=5)

    assert len(records) == 1
    assert records[0].content == "remember this"
    assert records[0].kind == "insight"


def test_history_round_trip_ordering():
    graph = FakeGraph(
        responses=[
            (
                "ORDER BY m.seq",
                [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            )
        ]
    )
    memory = GraphMemory(graph)

    memory.ensure_session("s1")
    memory.append_message("s1", "user", "hi")
    history = memory.load_history("s1")

    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    # session + message writes were issued against the meta namespace
    assert any("Cyph3rSession" in q for q in graph.write_queries())
    assert any("Cyph3rMessage" in q for q in graph.write_queries())
