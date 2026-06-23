"""Assemble a ready-to-use :class:`GraphAgent` from settings.

Kept separate from ``agent.py`` so the agent module stays free of the heavy provider /
driver imports — the agent and its collaborators can be unit tested with fakes without
``anthropic`` or ``neo4j`` installed.
"""

from __future__ import annotations

from .agent import GraphAgent
from .config import Settings, load_settings
from .graph import Neo4jClient
from .memory import GraphMemory
from .schema import SchemaState
from .tools import build_registry


def build_client(settings: Settings | None = None) -> Neo4jClient:
    """Construct just the Neo4j client (no LLM) — enough to read/view the graph."""
    settings = settings or load_settings()
    client = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    client.ensure_meta_constraints(settings.cyph3r_meta_label_prefix)
    return client


def build_agent(
    settings: Settings | None = None,
    client: Neo4jClient | None = None,
) -> tuple[GraphAgent, Neo4jClient]:
    """Construct the agent and the underlying client (caller owns ``client.close()``).

    Pass an existing ``client`` to reuse one connection (e.g. when the viewer already
    opened a client and we additionally want the LLM agent).
    """
    settings = settings or load_settings()
    client = client or build_client(settings)

    provider = _build_provider(settings)
    schema_state = SchemaState(client, settings.cyph3r_meta_label_prefix)
    memory = GraphMemory(client, settings.cyph3r_meta_label_prefix)
    registry = build_registry(client, schema_state, memory, settings.cyph3r_meta_label_prefix)

    agent = GraphAgent(
        provider=provider,
        registry=registry,
        memory=memory,
        schema_state=schema_state,
        client=client,
        meta_prefix=settings.cyph3r_meta_label_prefix,
        max_steps=settings.cyph3r_max_steps,
        max_repair_attempts=settings.cyph3r_max_repair_attempts,
    )
    return agent, client


def _build_provider(settings: Settings):
    provider = settings.cyph3r_llm_provider.lower()
    if provider == "anthropic":
        from .llm.anthropic import AnthropicProvider

        return AnthropicProvider(
            model=settings.cyph3r_model,
            api_key=settings.anthropic_api_key,
        )
    raise ValueError(
        f"Unsupported LLM provider {settings.cyph3r_llm_provider!r}. "
        "Only 'anthropic' is implemented; add a new LLMProvider to extend."
    )
