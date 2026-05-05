from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from temporial_graph_rag.collection_naming import (
    to_external_collection_name,
    to_internal_collection_name,
)


@dataclass(frozen=True)
class CollectionBinding:
    collection_name: str
    ontology_id: str


class CollectionRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, CollectionBinding] = {}

    def create(self, collection_name: str, ontology_id: str) -> CollectionBinding:
        internal = to_internal_collection_name(collection_name)
        existing = self._bindings.get(internal)
        if existing and existing.ontology_id != ontology_id:
            raise ValueError(
                f"Collection '{to_external_collection_name(internal)}' already exists with ontology '{existing.ontology_id}'"
            )
        binding = CollectionBinding(collection_name=internal, ontology_id=ontology_id)
        self._bindings[internal] = binding
        return binding

    def get(self, collection_name: str) -> CollectionBinding | None:
        return self._bindings.get(to_internal_collection_name(collection_name))

    def ensure_binding(self, collection_name: str, ontology_id: str) -> None:
        internal = to_internal_collection_name(collection_name)
        existing = self._bindings.get(internal)
        if not existing:
            raise KeyError(f"Collection '{collection_name}' does not exist")
        if existing.ontology_id != ontology_id:
            raise ValueError(
                f"Collection '{collection_name}' is bound to ontology '{existing.ontology_id}', not '{ontology_id}'"
            )

    def clear(self) -> None:
        self._bindings.clear()

    def list_bindings(self) -> list[CollectionBinding]:
        return list(self._bindings.values())

    def backend_kind(self) -> str:
        return "memory"


class RagCollectionStore(Protocol):
    def upsert_rag_collection(self, *, collection_name: str, ontology_id: str) -> dict[str, Any]: ...
    def get_rag_collection(self, *, collection_name: str) -> dict[str, Any] | None: ...
    def list_rag_collections(self) -> list[dict[str, Any]]: ...
    def clear_rag_collections(self) -> None: ...


class Neo4jCollectionRegistry:
    """Persistent registry backed by Neo4j RagCollection nodes."""

    def __init__(self, store: RagCollectionStore) -> None:
        self._store = store

    def create(self, collection_name: str, ontology_id: str) -> CollectionBinding:
        existing = self.get(collection_name)
        if existing and existing.ontology_id != ontology_id:
            raise ValueError(
                f"Collection '{to_external_collection_name(existing.collection_name)}' already exists with ontology '{existing.ontology_id}'"
            )
        row = self._store.upsert_rag_collection(collection_name=collection_name, ontology_id=ontology_id)
        return CollectionBinding(
            collection_name=str(row.get("collection_name") or collection_name),
            ontology_id=str(row.get("ontology_id") or ontology_id),
        )

    def get(self, collection_name: str) -> CollectionBinding | None:
        row = self._store.get_rag_collection(collection_name=collection_name)
        if row is None:
            return None
        return CollectionBinding(
            collection_name=str(row.get("collection_name") or collection_name),
            ontology_id=str(row.get("ontology_id") or ""),
        )

    def ensure_binding(self, collection_name: str, ontology_id: str) -> None:
        existing = self.get(collection_name)
        if not existing:
            raise KeyError(f"Collection '{collection_name}' does not exist")
        if existing.ontology_id != ontology_id:
            raise ValueError(
                f"Collection '{collection_name}' is bound to ontology '{existing.ontology_id}', not '{ontology_id}'"
            )

    def clear(self) -> None:
        self._store.clear_rag_collections()

    def list_bindings(self) -> list[CollectionBinding]:
        return [
            CollectionBinding(
                collection_name=str(r.get("collection_name") or ""),
                ontology_id=str(r.get("ontology_id") or ""),
            )
            for r in self._store.list_rag_collections()
        ]

    def backend_kind(self) -> str:
        return "neo4j"


class MutableCollectionRegistry:
    """Stable object reference that can swap backend implementation at runtime."""

    def __init__(self, backend: CollectionRegistry | Neo4jCollectionRegistry) -> None:
        self._backend = backend

    def set_backend(self, backend: CollectionRegistry | Neo4jCollectionRegistry) -> None:
        self._backend = backend

    def create(self, collection_name: str, ontology_id: str) -> CollectionBinding:
        return self._backend.create(collection_name, ontology_id)

    def get(self, collection_name: str) -> CollectionBinding | None:
        return self._backend.get(collection_name)

    def ensure_binding(self, collection_name: str, ontology_id: str) -> None:
        self._backend.ensure_binding(collection_name, ontology_id)

    def clear(self) -> None:
        self._backend.clear()

    def list_bindings(self) -> list[CollectionBinding]:
        return self._backend.list_bindings()

    def backend_kind(self) -> str:
        kind = getattr(self._backend, "backend_kind", None)
        if callable(kind):
            return str(kind())
        return "unknown"
