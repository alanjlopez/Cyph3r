"""Graph-native memory.

Sessions, conversation history, and durable learnings live inside Neo4j itself as
nodes in a reserved namespace (``Cyph3rSession`` / ``Cyph3rMessage`` / ``Cyph3rMemory`` /
``Cyph3rInsight``). Memories link out to the domain entities they concern via ``:ABOUT``
relationships so recall can be scoped to the entities currently in play.

Keeping everything in Neo4j means a single datastore and lets the agent query its own
memory with the same tools it uses on the domain graph.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .graph import GraphClient, escape_label


@dataclass
class MemoryRecord:
    id: str
    kind: str
    content: str


class GraphMemory:
    """CRUD for the agent's bookkeeping subgraph."""

    def __init__(self, client: GraphClient, meta_prefix: str = "Cyph3r") -> None:
        self.client = client
        self.prefix = meta_prefix
        self.session_label = escape_label(f"{meta_prefix}Session")
        self.message_label = escape_label(f"{meta_prefix}Message")
        self.memory_label = escape_label(f"{meta_prefix}Memory")
        self.insight_label = escape_label(f"{meta_prefix}Insight")

    # -- sessions & conversation history -------------------------------------

    def ensure_session(self, session_id: str) -> None:
        self.client.write(
            f"MERGE (s:`{self.session_label}` {{id: $sid}}) "
            f"ON CREATE SET s.created_at = timestamp()",
            {"sid": session_id},
        )

    def append_message(self, session_id: str, role: str, content: str) -> None:
        self.client.write(
            f"MATCH (s:`{self.session_label}` {{id: $sid}}) "
            f"OPTIONAL MATCH (s)-[:HAS_MESSAGE]->(m:`{self.message_label}`) "
            f"WITH s, count(m) AS seq "
            f"CREATE (s)-[:HAS_MESSAGE]->"
            f"(:`{self.message_label}` {{role: $role, content: $content, seq: seq, "
            f"created_at: timestamp()}})",
            {"sid": session_id, "role": role, "content": content},
        )

    def load_history(self, session_id: str) -> list[dict[str, str]]:
        rows = self.client.read(
            f"MATCH (s:`{self.session_label}` {{id: $sid}})-[:HAS_MESSAGE]->"
            f"(m:`{self.message_label}`) "
            f"RETURN m.role AS role, m.content AS content ORDER BY m.seq",
            {"sid": session_id},
        )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    # -- durable learnings ---------------------------------------------------

    def record_memory(
        self,
        content: str,
        about: list[str] | None = None,
        kind: str = "memory",
    ) -> str:
        """Store a memory/insight and optionally link it to domain entities by name.

        ``about`` is a list of entity names; each is matched against ``n.name`` or
        ``n.id`` on any *domain* node and connected via ``:ABOUT``.
        """
        label = self.insight_label if kind == "insight" else self.memory_label
        memory_id = str(uuid.uuid4())
        self.client.write(
            f"CREATE (m:`{label}` {{id: $id, kind: $kind, content: $content, "
            f"created_at: timestamp()}})",
            {"id": memory_id, "kind": kind, "content": content},
        )
        if about:
            self.client.write(
                f"MATCH (m:`{label}` {{id: $id}}) "
                f"MATCH (n) WHERE (n.name IN $about OR n.id IN $about) "
                f"AND none(l IN labels(n) WHERE l STARTS WITH $prefix) "
                f"MERGE (m)-[:ABOUT]->(n)",
                {"id": memory_id, "about": about, "prefix": self.prefix},
            )
        return memory_id

    def recall(self, about: list[str] | None = None, limit: int = 10) -> list[MemoryRecord]:
        """Fetch recent memories, optionally scoped to the given entity names."""
        limit = max(1, min(int(limit), 100))
        labels = f"`{self.memory_label}`|`{self.insight_label}`"
        if about:
            rows = self.client.read(
                f"MATCH (m:{labels})-[:ABOUT]->(n) "
                f"WHERE (n.name IN $about OR n.id IN $about) "
                f"RETURN DISTINCT m.id AS id, m.kind AS kind, m.content AS content, "
                f"m.created_at AS created_at "
                f"ORDER BY created_at DESC LIMIT {limit}",
                {"about": about},
            )
        else:
            rows = self.client.read(
                f"MATCH (m:{labels}) "
                f"RETURN m.id AS id, m.kind AS kind, m.content AS content, "
                f"m.created_at AS created_at "
                f"ORDER BY created_at DESC LIMIT {limit}",
            )
        return [
            MemoryRecord(id=r["id"], kind=r.get("kind") or "memory", content=r["content"])
            for r in rows
        ]
