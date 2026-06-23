from cyph3r.schema import SchemaModel, introspect, is_meta_label
from tests.fakes import FakeGraph


def test_is_meta_label():
    assert is_meta_label("Cyph3rSession", "Cyph3r")
    assert is_meta_label("Cyph3rMemory", "Cyph3r")
    assert not is_meta_label("Person", "Cyph3r")
    assert not is_meta_label("Movie", "Cyph3r")


def test_render_includes_labels_and_relationships():
    model = SchemaModel(
        labels={"Person": ["age", "name"]},
        relationships=[{"start": "Person", "type": "KNOWS", "end": "Person"}],
    )
    text = model.render()
    assert "(:Person) {age, name}" in text
    assert "(:Person)-[:KNOWS]->(:Person)" in text


def test_render_empty_graph():
    assert "empty" in SchemaModel().render().lower()


def test_introspect_excludes_meta_labels_and_builds_model():
    graph = FakeGraph(
        responses=[
            ("db.labels()", [{"label": "Person"}, {"label": "Cyph3rSession"}]),
            ("UNWIND keys(n)", [{"keys": ["name", "age"]}]),
            (
                "RETURN DISTINCT la AS start",
                [{"start": ["Person"], "type": "KNOWS", "end": ["Person"]}],
            ),
        ]
    )
    model = introspect(graph, meta_prefix="Cyph3r")

    # The agent's own bookkeeping label must never appear in the domain model.
    assert "Cyph3rSession" not in model.labels
    assert model.labels == {"Person": ["age", "name"]}
    assert {"start": "Person", "type": "KNOWS", "end": "Person"} in model.relationships
