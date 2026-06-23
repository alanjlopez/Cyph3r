from cyph3r.agent import GraphAgent
from cyph3r.llm.base import ToolCall, TurnResult
from cyph3r.memory import GraphMemory
from cyph3r.schema import SchemaState
from cyph3r.tools import build_registry
from tests.fakes import FakeGraph, FakeProvider


def _assistant(blocks=None):
    return {"role": "assistant", "content": blocks or []}


def _build_agent(graph, provider):
    schema_state = SchemaState(graph, "Cyph3r")
    memory = GraphMemory(graph, "Cyph3r")
    registry = build_registry(graph, schema_state, memory, "Cyph3r")
    return GraphAgent(
        provider=provider,
        registry=registry,
        memory=memory,
        schema_state=schema_state,
        client=graph,
        meta_prefix="Cyph3r",
    )


def test_agent_self_repairs_failed_cypher_and_records_insight():
    # The graph rejects any write containing BADQUERY, accepts the rest.
    graph = FakeGraph(write_failures=["BADQUERY"])
    provider = FakeProvider(
        [
            TurnResult(
                _assistant(),
                tool_calls=[ToolCall("t1", "write_cypher", {"query": "BADQUERY"})],
                stop_reason="tool_use",
            ),
            TurnResult(
                _assistant(),
                tool_calls=[
                    ToolCall("t2", "write_cypher", {"query": "CREATE (:Person {name:'Alice'})"})
                ],
                stop_reason="tool_use",
            ),
            TurnResult(_assistant(), tool_calls=[], text="Done.", stop_reason="end_turn"),
        ]
    )
    agent = _build_agent(graph, provider)

    result = agent.chat("s1", "Create a Person named Alice")

    assert result.answer == "Done."

    write_steps = [s for s in result.steps if s.tool == "write_cypher"]
    assert len(write_steps) == 2
    assert write_steps[0].is_error is True  # first attempt failed
    assert write_steps[1].is_error is False  # repaired retry succeeded

    # Both attempts actually reached the graph (proving the repair retry happened).
    assert any("BADQUERY" in q for q in graph.write_queries())
    assert any("CREATE (:Person" in q for q in graph.write_queries())

    # The agent learned from the session by recording an insight.
    assert any("Cyph3rInsight" in q for q in graph.write_queries())


def test_agent_stops_after_repeated_unrepairable_errors():
    graph = FakeGraph(write_failures=["CREATE"])
    bad_turn = lambda i: TurnResult(  # noqa: E731
        _assistant(),
        tool_calls=[ToolCall(f"t{i}", "write_cypher", {"query": f"CREATE (:N{i})"})],
        stop_reason="tool_use",
    )
    provider = FakeProvider([bad_turn(i) for i in range(10)])
    agent = _build_agent(graph, provider)
    agent.max_repair_attempts = 2

    result = agent.chat("s1", "keep trying")

    assert "repeated tool errors" in result.answer.lower()
    # Stopped early rather than exhausting all scripted turns.
    assert len(result.steps) <= 4
