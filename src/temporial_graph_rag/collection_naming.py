"""Storage-level collection names vs external API names.

All HTTP payloads and path segments use a logical collection name. Neo4j, registry
bindings, and in-graph ``collection_name`` properties use ``tg_graph_<logical>``.
"""

from __future__ import annotations

__all__ = [
    "TG_GRAPH_COLLECTION_PREFIX",
    "to_internal_collection_name",
    "to_external_collection_name",
    "strip_collection_names_in_json",
]

TG_GRAPH_COLLECTION_PREFIX: str = "tg_graph_"


def to_internal_collection_name(name: str) -> str:
    """Normalize logical or already-internal name to the canonical stored form."""
    s = (name or "").strip()
    if not s:
        return s
    while s.startswith(TG_GRAPH_COLLECTION_PREFIX):
        s = s[len(TG_GRAPH_COLLECTION_PREFIX) :]
    if not s:
        return s
    return TG_GRAPH_COLLECTION_PREFIX + s


def to_external_collection_name(name: str) -> str:
    """Return logical collection name for API clients (strip one layer of prefix)."""
    s = (name or "").strip()
    if s.startswith(TG_GRAPH_COLLECTION_PREFIX):
        return s[len(TG_GRAPH_COLLECTION_PREFIX) :]
    return s


def strip_collection_names_in_json(obj: object) -> object:
    """Recursively rewrite ``collection_name`` string fields for outbound JSON."""
    if isinstance(obj, dict):
        out: dict[object, object] = {}
        for k, v in obj.items():
            nv = strip_collection_names_in_json(v)
            if k == "collection_name" and isinstance(nv, str):
                nv = to_external_collection_name(nv)
            out[k] = nv
        return out
    if isinstance(obj, list):
        return [strip_collection_names_in_json(x) for x in obj]
    return obj
