from __future__ import annotations

from temporial_graph_rag.collection_naming import to_external_collection_name, to_internal_collection_name
from temporial_graph_rag.collections.registry import Neo4jCollectionRegistry


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def upsert_rag_collection(self, *, collection_name: str, ontology_id: str):
        i = to_internal_collection_name(collection_name)
        self.rows[i] = ontology_id
        return {"collection_name": i, "ontology_id": ontology_id}

    def get_rag_collection(self, *, collection_name: str):
        i = to_internal_collection_name(collection_name)
        oid = self.rows.get(i)
        if oid is None:
            return None
        return {"collection_name": i, "ontology_id": oid}

    def list_rag_collections(self):
        return [{"collection_name": k, "ontology_id": v} for k, v in sorted(self.rows.items())]

    def clear_rag_collections(self) -> None:
        self.rows.clear()


def test_persistent_registry_create_and_get() -> None:
    reg = Neo4jCollectionRegistry(_FakeStore())
    b = reg.create("stocks:nse:INFY", "company_events.v1")
    assert b.collection_name == to_internal_collection_name("stocks:nse:INFY")
    assert to_external_collection_name(b.collection_name) == "stocks:nse:INFY"
    assert b.ontology_id == "company_events.v1"
    got = reg.get("stocks:nse:INFY")
    assert got is not None
    assert got.ontology_id == "company_events.v1"


def test_persistent_registry_rejects_ontology_change() -> None:
    reg = Neo4jCollectionRegistry(_FakeStore())
    reg.create("stocks:nse:INFY", "company_events.v1")
    try:
        reg.create("stocks:nse:INFY", "another.v1")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "already exists with ontology" in str(exc)


def test_persistent_registry_ensure_binding_and_list() -> None:
    reg = Neo4jCollectionRegistry(_FakeStore())
    reg.create("stocks:nse:INFY", "company_events.v1")
    reg.create("stocks:nse:TCS", "company_events.v1")
    reg.ensure_binding("stocks:nse:INFY", "company_events.v1")
    rows = reg.list_bindings()
    log = sorted(to_external_collection_name(r.collection_name) for r in rows)
    assert log == ["stocks:nse:INFY", "stocks:nse:TCS"]

