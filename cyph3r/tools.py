"""The tool surface exposed to the LLM.

Each tool wraps a lower-level capability (schema, raw Cypher, traversal, memory,
analysis), returns a JSON-serializable result, and turns any backend exception into an
error payload so the agent's self-repair loop can react instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import improve, traversal
from .graph import GraphClient
from .llm.base import ToolSpec
from .memory import GraphMemory
from .schema import SchemaState


@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[[dict[str, Any]], Any]


class ToolRegistry:
    """Holds the tools and executes calls, normalizing errors."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.spec.name: t for t in tools}

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        """Run a tool. Returns ``(result, is_error)``."""
        tool = self._tools.get(name)
        if tool is None:
            return ({"error": f"Unknown tool: {name}"}, True)
        try:
            return (tool.handler(arguments or {}), False)
        except Exception as exc:  # surfaced to the model for self-repair
            payload: dict[str, Any] = {"error": str(exc)}
            code = getattr(exc, "code", None)
            if code:
                payload["code"] = code
            return (payload, True)


def build_registry(
    client: GraphClient,
    schema_state: SchemaState,
    memory: GraphMemory,
    meta_prefix: str = "Cyph3r",
) -> ToolRegistry:
    """Wire the concrete capabilities into a registry of LLM-callable tools."""

    def get_schema(_: dict[str, Any]) -> Any:
        return {"schema": schema_state.refresh().render()}

    def read_cypher(args: dict[str, Any]) -> Any:
        rows = client.read(args["query"], args.get("parameters") or {})
        return {"rows": rows, "count": len(rows)}

    def write_cypher(args: dict[str, Any]) -> Any:
        result = client.write(args["query"], args.get("parameters") or {})
        schema_state.mark_stale()
        return result

    def traverse(args: dict[str, Any]) -> Any:
        return traversal.neighbors(
            client,
            key=args.get("key", "name"),
            value=args["value"],
            label=args.get("label"),
            rel_types=args.get("rel_types"),
            direction=args.get("direction", "both"),
            max_depth=args.get("max_depth", 1),
            limit=args.get("limit", 100),
            meta_prefix=meta_prefix,
        )

    def find_path(args: dict[str, Any]) -> Any:
        return traversal.find_path(
            client,
            from_key=args.get("from_key", "name"),
            from_value=args["from_value"],
            to_key=args.get("to_key", "name"),
            to_value=args["to_value"],
            max_depth=args.get("max_depth", 6),
        )

    def create_relationship(args: dict[str, Any]) -> Any:
        result = traversal.create_relationship(
            client,
            from_key=args.get("from_key", "name"),
            from_value=args["from_value"],
            to_key=args.get("to_key", "name"),
            to_value=args["to_value"],
            rel_type=args["rel_type"],
            properties=args.get("properties"),
        )
        schema_state.mark_stale()
        return result

    def remember(args: dict[str, Any]) -> Any:
        memory_id = memory.record_memory(
            content=args["content"],
            about=args.get("about"),
            kind=args.get("kind", "memory"),
        )
        return {"recorded": True, "id": memory_id}

    def recall(args: dict[str, Any]) -> Any:
        records = memory.recall(about=args.get("about"), limit=args.get("limit", 10))
        return {"memories": [{"kind": r.kind, "content": r.content} for r in records]}

    def analyze_graph(_: dict[str, Any]) -> Any:
        findings = improve.analyze(client, meta_prefix=meta_prefix)
        return {
            "orphans": findings.orphans,
            "duplicates": findings.duplicates,
            "summary": findings.summary(),
        }

    tools = [
        Tool(
            ToolSpec(
                "get_schema",
                "Return the current domain-graph schema (labels, properties, "
                "relationship patterns, constraints). Call this before writing Cypher "
                "against an unfamiliar graph.",
                {"type": "object", "properties": {}},
            ),
            get_schema,
        ),
        Tool(
            ToolSpec(
                "read_cypher",
                "Run a read-only Cypher query and return the rows. Use for any MATCH/"
                "RETURN that does not modify data.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "A read-only Cypher query."},
                        "parameters": {
                            "type": "object",
                            "description": "Optional query parameters.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            read_cypher,
        ),
        Tool(
            ToolSpec(
                "write_cypher",
                "Run a write Cypher query (CREATE/MERGE/SET/DELETE) in a transaction "
                "and return the result summary. Prefer MERGE for idempotency.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "A write Cypher query."},
                        "parameters": {
                            "type": "object",
                            "description": "Optional query parameters.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            write_cypher,
        ),
        Tool(
            ToolSpec(
                "traverse",
                "Expand outward from a node (matched by a property) to its neighbors, "
                "up to max_depth hops. Use for exploring how an entity connects.",
                {
                    "type": "object",
                    "properties": {
                        "value": {"description": "Property value identifying the start node."},
                        "key": {"type": "string", "description": "Match property (default 'name')."},
                        "label": {"type": "string", "description": "Optional start-node label."},
                        "rel_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Restrict to these relationship types.",
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["out", "in", "both"],
                            "description": "Traversal direction (default 'both').",
                        },
                        "max_depth": {"type": "integer", "description": "Hops to expand (1-6)."},
                        "limit": {"type": "integer", "description": "Max neighbors to return."},
                    },
                    "required": ["value"],
                },
            ),
            traverse,
        ),
        Tool(
            ToolSpec(
                "find_path",
                "Find the shortest path between two nodes matched by property values.",
                {
                    "type": "object",
                    "properties": {
                        "from_value": {"description": "Start node property value."},
                        "to_value": {"description": "End node property value."},
                        "from_key": {"type": "string", "description": "Start match property (default 'name')."},
                        "to_key": {"type": "string", "description": "End match property (default 'name')."},
                        "max_depth": {"type": "integer", "description": "Max path length (1-6)."},
                    },
                    "required": ["from_value", "to_value"],
                },
            ),
            find_path,
        ),
        Tool(
            ToolSpec(
                "create_relationship",
                "Idempotently connect two existing nodes with a typed relationship "
                "(MERGE-based). Match endpoints by a property value.",
                {
                    "type": "object",
                    "properties": {
                        "from_value": {"description": "Start node property value."},
                        "to_value": {"description": "End node property value."},
                        "rel_type": {"type": "string", "description": "Relationship type, e.g. KNOWS."},
                        "from_key": {"type": "string", "description": "Start match property (default 'name')."},
                        "to_key": {"type": "string", "description": "End match property (default 'name')."},
                        "properties": {"type": "object", "description": "Relationship properties."},
                    },
                    "required": ["from_value", "to_value", "rel_type"],
                },
            ),
            create_relationship,
        ),
        Tool(
            ToolSpec(
                "remember",
                "Persist a durable learning or fact into the agent's graph-native "
                "memory, optionally linked to the domain entities it concerns. Use "
                "'insight' for reusable lessons; 'memory' for facts.",
                {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The text to remember."},
                        "about": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names/ids of related domain entities.",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["memory", "insight"],
                            "description": "Memory kind (default 'memory').",
                        },
                    },
                    "required": ["content"],
                },
            ),
            remember,
        ),
        Tool(
            ToolSpec(
                "recall",
                "Retrieve relevant memories/insights from graph-native memory, "
                "optionally scoped to specific entity names.",
                {
                    "type": "object",
                    "properties": {
                        "about": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Scope recall to these entity names/ids.",
                        },
                        "limit": {"type": "integer", "description": "Max memories to return."},
                    },
                },
            ),
            recall,
        ),
        Tool(
            ToolSpec(
                "analyze_graph",
                "Scan the domain graph for improvement opportunities: orphan nodes and "
                "duplicate candidates. Returns findings to act on with write_cypher / "
                "create_relationship.",
                {"type": "object", "properties": {}},
            ),
            analyze_graph,
        ),
    ]
    return ToolRegistry(tools)
