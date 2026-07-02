"""Live-schema introspection and an enriched, cached schema model.

The model describes only the *domain* graph: every label in the reserved meta
namespace (default prefix ``Cyph3r``) is excluded so the agent never mistakes its own
bookkeeping for user data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import GraphClient, escape_label


def is_meta_label(label: str, meta_prefix: str) -> bool:
    """True if a label belongs to the agent's reserved namespace."""
    return bool(meta_prefix) and label.startswith(meta_prefix)


@dataclass
class SchemaModel:
    """A compact, rendered-to-text view of the domain graph's structure."""

    labels: dict[str, list[str]] = field(default_factory=dict)  # label -> property keys
    relationships: list[dict[str, str]] = field(default_factory=list)  # {start, type, end}
    constraints: list[str] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.labels and not self.relationships

    def render(self) -> str:
        """Render the model as a short, token-efficient text block for the prompt."""
        if self.is_empty():
            return "The graph is currently empty (no domain nodes or relationships)."

        lines: list[str] = ["Node labels and their properties:"]
        for label in sorted(self.labels):
            props = ", ".join(self.labels[label]) or "(no sampled properties)"
            lines.append(f"  (:{label}) {{{props}}}")

        if self.relationships:
            lines.append("Relationship patterns:")
            seen: set[str] = set()
            for rel in self.relationships:
                pattern = f"  (:{rel['start']})-[:{rel['type']}]->(:{rel['end']})"
                if pattern not in seen:
                    seen.add(pattern)
                    lines.append(pattern)

        if self.constraints:
            lines.append("Constraints:")
            lines.extend(f"  {c}" for c in self.constraints)
        if self.indexes:
            lines.append("Indexes:")
            lines.extend(f"  {i}" for i in self.indexes)
        return "\n".join(lines)


def introspect(
    client: GraphClient,
    meta_prefix: str = "Cyph3r",
    sample_limit: int = 200,
) -> SchemaModel:
    """Build a :class:`SchemaModel` by querying the live database.

    Each section is best-effort: differences across Neo4j versions (e.g. ``SHOW
    CONSTRAINTS`` availability) never abort introspection.
    """
    sample_limit = max(1, min(int(sample_limit), 5000))
    model = SchemaModel()

    labels = _safe_read(client, "CALL db.labels() YIELD label RETURN label")
    domain_labels = [
        row["label"]
        for row in labels
        if not is_meta_label(row["label"], meta_prefix)
    ]

    for label in domain_labels:
        safe = escape_label(label)
        rows = _safe_read(
            client,
            f"MATCH (n:`{safe}`) WITH n LIMIT {sample_limit} "
            f"UNWIND keys(n) AS k RETURN collect(DISTINCT k) AS keys",
        )
        keys = rows[0]["keys"] if rows and rows[0].get("keys") else []
        model.labels[label] = sorted(keys)

    model.relationships = _relationship_patterns(client, meta_prefix, sample_limit)
    model.constraints = _safe_descriptions(client, "SHOW CONSTRAINTS")
    model.indexes = _safe_descriptions(client, "SHOW INDEXES")
    return model


def _relationship_patterns(
    client: GraphClient,
    meta_prefix: str,
    sample_limit: int,
) -> list[dict[str, str]]:
    rows = _safe_read(
        client,
        f"MATCH (a)-[r]->(b) WITH labels(a) AS la, type(r) AS t, labels(b) AS lb "
        f"LIMIT {sample_limit} RETURN DISTINCT la AS start, t AS type, lb AS end",
    )
    patterns: list[dict[str, str]] = []
    for row in rows:
        start = _first_domain_label(row.get("start"), meta_prefix)
        end = _first_domain_label(row.get("end"), meta_prefix)
        rel_type = row.get("type")
        if start and end and rel_type:
            patterns.append({"start": start, "type": rel_type, "end": end})
    return patterns


def _first_domain_label(labels: Any, meta_prefix: str) -> str | None:
    if not labels:
        return None
    for label in labels:
        if not is_meta_label(label, meta_prefix):
            return label
    return None


def _safe_read(client: GraphClient, query: str) -> list[dict[str, Any]]:
    try:
        return client.read(query)
    except Exception:
        return []


def _safe_descriptions(client: GraphClient, query: str) -> list[str]:
    out: list[str] = []
    for row in _safe_read(client, query):
        name = row.get("name") or row.get("description")
        if name:
            out.append(str(name))
    return out


class SchemaState:
    """Holds the cached schema model and refreshes it lazily after writes."""

    def __init__(self, client: GraphClient, meta_prefix: str = "Cyph3r") -> None:
        self._client = client
        self._meta_prefix = meta_prefix
        self._model: SchemaModel | None = None

    def refresh(self) -> SchemaModel:
        self._model = introspect(self._client, self._meta_prefix)
        return self._model

    def get(self) -> SchemaModel:
        if self._model is None:
            return self.refresh()
        return self._model

    def mark_stale(self) -> None:
        self._model = None

    def render(self) -> str:
        return self.get().render()
