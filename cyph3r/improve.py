"""Continuous-improvement engine.

``analyze`` inspects the domain graph for enrichment opportunities (orphan nodes,
duplicate candidates, sparse relationships). The agent then proposes and auto-applies
Cypher to act on the findings (see :meth:`cyph3r.agent.GraphAgent.improve`). Pure
helpers here build deterministic fix Cypher so they can be unit tested without an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import GraphClient

_DEFAULT_LIMIT = 50


@dataclass
class Findings:
    orphans: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.orphans and not self.duplicates

    def summary(self) -> str:
        lines: list[str] = []
        if self.orphans:
            lines.append(f"{len(self.orphans)} orphan node(s) with no relationships:")
            for o in self.orphans:
                lines.append(f"  - labels={o.get('labels')} props={o.get('props')}")
        if self.duplicates:
            lines.append(f"{len(self.duplicates)} duplicate group(s) (same label + name):")
            for d in self.duplicates:
                lines.append(
                    f"  - labels={d.get('labels')} name={d.get('name')!r} "
                    f"ids={d.get('ids')}"
                )
        if not lines:
            return "No structural issues detected."
        return "\n".join(lines)


def analyze(
    client: GraphClient,
    meta_prefix: str = "Cyph3r",
    limit: int = _DEFAULT_LIMIT,
) -> Findings:
    """Scan the domain graph for orphans and duplicate candidates."""
    cap = max(1, min(int(limit), 500))

    orphans = _safe_read(
        client,
        "MATCH (n) WHERE NOT (n)--() "
        "AND none(l IN labels(n) WHERE l STARTS WITH $prefix) "
        f"RETURN labels(n) AS labels, properties(n) AS props, id(n) AS id LIMIT {cap}",
        {"prefix": meta_prefix},
    )

    duplicates = _safe_read(
        client,
        "MATCH (n) WHERE n.name IS NOT NULL "
        "AND none(l IN labels(n) WHERE l STARTS WITH $prefix) "
        "WITH labels(n) AS labels, n.name AS name, collect(id(n)) AS ids "
        "WHERE size(ids) > 1 "
        f"RETURN labels, name, ids LIMIT {cap}",
        {"prefix": meta_prefix},
    )

    return Findings(orphans=orphans, duplicates=duplicates)


def merge_duplicates_cypher() -> str:
    """Cypher to merge a set of duplicate node ids (passed as ``$ids``).

    Uses APOC; if APOC is unavailable the write transaction fails and is rolled back,
    which the propose-then-auto-apply flow reports rather than corrupting data.
    """
    return (
        "MATCH (n) WHERE id(n) IN $ids "
        "WITH collect(n) AS nodes "
        "CALL apoc.refactor.mergeNodes(nodes, "
        "{properties: 'combine', mergeRels: true}) YIELD node "
        "RETURN id(node) AS id"
    )


def _safe_read(
    client: GraphClient,
    query: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        return client.read(query, params or {})
    except Exception:
        return []
