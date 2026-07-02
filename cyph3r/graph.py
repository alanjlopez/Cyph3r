"""Neo4j access layer.

``GraphClient`` is the structural interface the rest of the package depends on, so
tests can substitute a fake without a live database. ``Neo4jClient`` is the real
implementation; it imports the ``neo4j`` driver lazily so importing this module never
requires the driver to be installed.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GraphClient(Protocol):
    """Minimal surface every component needs from a graph backend."""

    def read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    def write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


def escape_label(label: str) -> str:
    """Escape a label/relationship-type for safe inlining inside backticks."""
    return label.replace("`", "``")


class Neo4jClient:
    """Thin wrapper over the official Neo4j Python driver.

    ``read`` runs in a read transaction and returns a list of record dicts.
    ``write`` runs in a write transaction and returns ``{"rows": [...], "counters": {...}}``.
    Neo4j errors propagate unchanged so the agent's self-repair loop can react to them.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        from neo4j import GraphDatabase  # lazy: only needed for a live connection

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        def _work(tx: Any) -> list[dict[str, Any]]:
            return [record.data() for record in tx.run(query, parameters or {})]

        with self._driver.session(database=self._database) as session:
            return session.execute_read(_work)

    def write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        def _work(tx: Any) -> dict[str, Any]:
            result = tx.run(query, parameters or {})
            rows = [record.data() for record in result]
            counters = result.consume().counters
            return {
                "rows": rows,
                "counters": {
                    "nodes_created": counters.nodes_created,
                    "nodes_deleted": counters.nodes_deleted,
                    "relationships_created": counters.relationships_created,
                    "relationships_deleted": counters.relationships_deleted,
                    "properties_set": counters.properties_set,
                    "labels_added": counters.labels_added,
                    "labels_removed": counters.labels_removed,
                },
            }

        with self._driver.session(database=self._database) as session:
            return session.execute_write(_work)

    def ensure_meta_constraints(self, meta_prefix: str = "Cyph3r") -> None:
        """Create uniqueness constraints for the agent's bookkeeping nodes."""
        for label, key in (
            (f"{meta_prefix}Session", "id"),
            (f"{meta_prefix}Memory", "id"),
        ):
            safe = escape_label(label)
            self.write(
                f"CREATE CONSTRAINT IF NOT EXISTS "
                f"FOR (n:`{safe}`) REQUIRE n.{key} IS UNIQUE"
            )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
