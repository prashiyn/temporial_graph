from __future__ import annotations

import os
from dataclasses import dataclass


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Neo4jSettings:
    enabled: bool
    uri: str
    user: str
    password: str
    database: str
    max_connection_pool_size: int
    store_embeddings: bool
    snapshot_vector_scan_limit: int
    snapshot_vector_index_name: str | None
    snapshot_embed_supersession_enabled: bool
    snapshot_embed_supersede_min_cosine: float
    snapshot_embed_supersede_max_targets: int
    snapshot_embed_supersede_same_chunk_only: bool

    @classmethod
    def from_env(cls) -> Neo4jSettings:
        index_raw = os.getenv("NEO4J_SNAPSHOT_VECTOR_INDEX", "") or ""
        index_name = index_raw.strip() or None
        return cls(
            enabled=_env_bool("NEO4J_ENABLED", False),
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", ""),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
            max_connection_pool_size=_as_int("NEO4J_MAX_CONNECTION_POOL_SIZE", 50),
            store_embeddings=_env_bool("NEO4J_STORE_EMBEDDINGS", False),
            snapshot_vector_scan_limit=_as_int("NEO4J_SNAPSHOT_VECTOR_SCAN_LIMIT", 2000),
            snapshot_vector_index_name=index_name,
            snapshot_embed_supersession_enabled=_env_bool("NEO4J_SNAPSHOT_EMBED_SUPERSESSION", True),
            snapshot_embed_supersede_min_cosine=_env_float("NEO4J_SNAPSHOT_EMBED_SUPERSEDE_MIN_COSINE", 0.92),
            snapshot_embed_supersede_max_targets=_as_int("NEO4J_SNAPSHOT_EMBED_SUPERSEDE_MAX_TARGETS", 5),
            snapshot_embed_supersede_same_chunk_only=_env_bool(
                "NEO4J_SNAPSHOT_EMBED_SUPERSEDE_SAME_CHUNK_ONLY",
                False,
            ),
        )
