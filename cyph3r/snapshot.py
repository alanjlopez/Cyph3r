"""Point-in-time snapshot of the live graph for visualization.

Returns a node/edge view suitable for vis-network (or any client): nodes carry a string
id, labels, and properties; edges connect ids that are present in the returned node set.
The domain/meta split is respected — the agent's ``:Cyph3r*`` namespace is excluded by
default (same filter used in ``schema.py`` / ``improve.py``).
"""

from __future__ import annotations

from typing import Any

from .graph import GraphClient

_MAX_NODES = 2000


def graph_snapshot(
    client: GraphClient,
    meta_prefix: str = "Cyph3r",
    node_limit: int = 300,
    include_meta: bool = False,
) -> dict[str, Any]:
    """Return ``{nodes, edges, counts, truncated}`` for the current graph."""
    limit = max(1, min(int(node_limit), _MAX_NODES))
    node_filter = (
        "true"
        if include_meta
        else "none(l IN labels(n) WHERE l STARTS WITH $prefix)"
    )

    node_rows = client.read(
        f"MATCH (n) WHERE {node_filter} "
        f"RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
        f"LIMIT {limit}",
        {"prefix": meta_prefix},
    )
    nodes = [
        {"id": row["id"], "labels": row.get("labels") or [], "properties": row.get("props") or {}}
        for row in node_rows
    ]
    ids = [n["id"] for n in nodes]

    edges: list[dict[str, Any]] = []
    if ids:
        edge_rows = client.read(
            "MATCH (a)-[r]->(b) "
            "WHERE elementId(a) IN $ids AND elementId(b) IN $ids "
            "RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target, "
            "type(r) AS type, properties(r) AS props",
            {"ids": ids},
        )
        edges = [
            {
                "id": row["id"],
                "source": row["source"],
                "target": row["target"],
                "type": row["type"],
                "properties": row.get("props") or {},
            }
            for row in edge_rows
        ]

    total_nodes = _count(client, node_filter, meta_prefix)
    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "nodes_shown": len(nodes),
            "nodes_total": total_nodes,
            "edges_shown": len(edges),
        },
        "truncated": total_nodes > len(nodes),
    }


def _count(client: GraphClient, node_filter: str, meta_prefix: str) -> int:
    rows = client.read(
        f"MATCH (n) WHERE {node_filter} RETURN count(n) AS total",
        {"prefix": meta_prefix},
    )
    return int(rows[0]["total"]) if rows else 0
