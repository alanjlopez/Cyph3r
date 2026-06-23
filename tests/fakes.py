"""In-memory fakes for testing without a live Neo4j or LLM."""

from __future__ import annotations

from typing import Any

from cyph3r.llm.base import TurnResult


class FakeNeo4jError(Exception):
    """Stand-in for neo4j.exceptions.Neo4jError, with a .code like the real driver."""

    def __init__(self, message: str, code: str = "Neo.ClientError.Statement.SyntaxError") -> None:
        super().__init__(message)
        self.code = code


class FakeGraph:
    """A graph client that returns canned read rows and records every query.

    ``responses`` maps a query substring to the rows returned for any query containing
    it (first match wins). ``write_failures`` lists substrings that should raise.
    """

    def __init__(
        self,
        responses: list[tuple[str, list[dict[str, Any]]]] | None = None,
        write_failures: list[str] | None = None,
    ) -> None:
        self.responses = responses or []
        self.write_failures = write_failures or []
        self.reads: list[tuple[str, dict[str, Any]]] = []
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.reads.append((query, parameters or {}))
        for substring, rows in self.responses:
            if substring in query:
                return rows
        return []

    def write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        self.writes.append((query, parameters or {}))
        for substring in self.write_failures:
            if substring in query:
                raise FakeNeo4jError(f"Simulated failure for query containing {substring!r}")
        return {"rows": [], "counters": {}}

    # convenience accessors for assertions
    def write_queries(self) -> list[str]:
        return [q for q, _ in self.writes]

    def read_queries(self) -> list[str]:
        return [q for q, _ in self.reads]


class FakeProvider:
    """An LLM provider that replays a scripted list of TurnResults."""

    def __init__(self, turns: list[TurnResult]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def run_turn(self, *, system: str, messages: list[dict[str, Any]], tools: Any) -> TurnResult:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        return self._turns.pop(0)
