"""First-class graph traversal helpers.

These build parameterized Cypher for neighbour expansion, path finding, and
relationship creation, returning compact JSON-friendly summaries. Property *values*
are always passed as parameters; only structural elements (labels, relationship
types, depth, direction) are inlined, and those are escaped/clamped.
"""

from __future__ import annotations

from typing import Any

from .graph import GraphClient, escape_label

_MAX_DEPTH = 6
_MAX_LIMIT = 1000


def _arrows(direction: str) -> tuple[str, str]:
    if direction == "out":
        return "-", "->"
    if direction == "in":
        return "<-", "-"
    return "-", "-"


def _type_filter(rel_types: list[str] | None) -> str:
    if not rel_types:
        return ""
    return ":" + "|".join(f"`{escape_label(t)}`" for t in rel_types)


def _start_pattern(label: str | None) -> str:
    if label:
        return f"(a:`{escape_label(label)}`)"
    return "(a)"


def neighbors(
    client: GraphClient,
    *,
    key: str,
    value: Any,
    label: str | None = None,
    rel_types: list[str] | None = None,
    direction: str = "both",
    max_depth: int = 1,
    limit: int = 100,
    meta_prefix: str = "Cyph3r",
) -> dict[str, Any]:
    """Expand outward from a matched start node, up to ``max_depth`` hops."""
    depth = max(1, min(int(max_depth), _MAX_DEPTH))
    cap = max(1, min(int(limit), _MAX_LIMIT))
    lhs, rhs = _arrows(direction)
    tf = _type_filter(rel_types)

    query = (
        f"MATCH {_start_pattern(label)} WHERE a[$key] = $value "
        f"MATCH (a){lhs}[r{tf}*1..{depth}]{rhs}(b) "
        f"WHERE none(l IN labels(b) WHERE l STARTS WITH $prefix) "
        f"RETURN DISTINCT labels(b) AS labels, properties(b) AS props, "
        f"[x IN r | type(x)] AS via LIMIT {cap}"
    )
    rows = client.read(query, {"key": key, "value": value, "prefix": meta_prefix})
    return {"start": {"key": key, "value": value}, "neighbors": rows, "count": len(rows)}


def find_path(
    client: GraphClient,
    *,
    from_key: str,
    from_value: Any,
    to_key: str,
    to_value: Any,
    max_depth: int = 6,
) -> dict[str, Any]:
    """Return the shortest path (if any) between two matched nodes."""
    depth = max(1, min(int(max_depth), _MAX_DEPTH))
    query = (
        "MATCH (a) WHERE a[$fk] = $fv "
        "MATCH (b) WHERE b[$tk] = $tv "
        f"MATCH p = shortestPath((a)-[*..{depth}]-(b)) "
        "RETURN [n IN nodes(p) | {labels: labels(n), props: properties(n)}] AS nodes, "
        "[r IN relationships(p) | type(r)] AS rels"
    )
    rows = client.read(
        query, {"fk": from_key, "fv": from_value, "tk": to_key, "tv": to_value}
    )
    if not rows:
        return {"found": False, "nodes": [], "rels": []}
    return {"found": True, "nodes": rows[0]["nodes"], "rels": rows[0]["rels"]}


def create_relationship(
    client: GraphClient,
    *,
    from_key: str,
    from_value: Any,
    to_key: str,
    to_value: Any,
    rel_type: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotently connect two matched nodes with a typed relationship."""
    safe_type = escape_label(rel_type)
    query = (
        "MATCH (a) WHERE a[$fk] = $fv "
        "MATCH (b) WHERE b[$tk] = $tv "
        f"MERGE (a)-[r:`{safe_type}`]->(b) "
        "SET r += $props "
        "RETURN type(r) AS type"
    )
    return client.write(
        query,
        {
            "fk": from_key,
            "fv": from_value,
            "tk": to_key,
            "tv": to_value,
            "props": properties or {},
        },
    )
