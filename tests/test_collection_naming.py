from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from temporial_graph_rag.api.main import app, registry
from temporial_graph_rag.collection_naming import (
    TG_GRAPH_COLLECTION_PREFIX,
    strip_collection_names_in_json,
    to_external_collection_name,
    to_internal_collection_name,
)


def test_to_internal_idempotent() -> None:
    assert to_internal_collection_name("acme") == f"{TG_GRAPH_COLLECTION_PREFIX}acme"
    assert (
        to_internal_collection_name(f"{TG_GRAPH_COLLECTION_PREFIX}acme")
        == f"{TG_GRAPH_COLLECTION_PREFIX}acme"
    )


def test_to_external_strips_once() -> None:
    inn = to_internal_collection_name("fund_a")
    assert to_external_collection_name(inn) == "fund_a"
    assert to_external_collection_name("acme") == "acme"


def test_strip_json_nested() -> None:
    inn = to_internal_collection_name("x")
    raw: dict = {
        "collection_name": inn,
        "hits": [{"collection_name": inn, "k": 1}],
        "nested": {"collection_name": {"not": "a string"}},
    }
    out = strip_collection_names_in_json(raw)
    assert out["collection_name"] == "x"
    assert out["hits"][0]["collection_name"] == "x"
    assert out["nested"]["collection_name"] == {"not": "a string"}


def test_memory_registry_stores_internal_names() -> None:
    from temporial_graph_rag.collections.registry import CollectionRegistry

    r = CollectionRegistry()
    r.create("tenant_a", "company_events.v1")
    got = r.get("tenant_a")
    assert got is not None
    assert got.collection_name == to_internal_collection_name("tenant_a")
    assert to_external_collection_name(got.collection_name) == "tenant_a"


def test_fastapi_json_roundtrip_logical_collection_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Middleware on ``app`` strips ``tg_graph_`` from JSON; paths stay logical."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    registry.clear()
    logical = f"boundary_test_{uuid.uuid4().hex[:8]}"
    with TestClient(app) as client:
        r = client.post(
            "/v1/collections",
            json={"collection_name": logical, "ontology_id": "company_events.v1"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["collection_name"] == logical
    got = registry.get(logical)
    assert got is not None
    assert got.collection_name == to_internal_collection_name(logical)
    assert to_external_collection_name(got.collection_name) == logical
