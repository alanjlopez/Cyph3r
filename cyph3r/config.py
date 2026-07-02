"""Runtime configuration, loaded from the environment / a .env file.

This module is the only place that depends on ``pydantic-settings``. Core modules
(``agent``, ``tools``, ``memory``, ...) accept plain primitives so they stay
import-light and easy to unit test without any settings machinery.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All knobs for connecting to Neo4j and driving the LLM.

    Field names map to upper-cased environment variables (e.g. ``neo4j_uri`` <-
    ``NEO4J_URI``); ``pydantic-settings`` matches them case-insensitively.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Neo4j connection
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"
    neo4j_database: str = "neo4j"

    # LLM
    cyph3r_llm_provider: str = "anthropic"
    cyph3r_model: str = "claude-opus-4-8"
    anthropic_api_key: str | None = None

    # Agent behaviour
    cyph3r_confirm_writes: bool = False
    cyph3r_max_repair_attempts: int = 3
    cyph3r_max_steps: int = 16
    cyph3r_meta_label_prefix: str = "Cyph3r"


@lru_cache
def load_settings() -> Settings:
    """Return a cached :class:`Settings` instance read from the environment."""
    return Settings()
