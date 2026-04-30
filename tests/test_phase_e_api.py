from __future__ import annotations

import os

from fastapi.testclient import TestClient

from temporial_graph_rag.api.main import app, registry


def setup_function() -> None:
    os.environ["NEO4J_ENABLED"] = "false"
    registry.clear()
    app.dependency_overrides.clear()


def test_list_collections_and_impact_prior_preview() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/collections").json() == []
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        rows = client.get("/v1/collections").json()
        assert len(rows) == 1
        assert rows[0]["collection_name"] == "acme"

        r = client.get(
            "/v1/collections/acme/impact-prior",
            params={"canonical_event": "LEGAL_REGULATORY", "canonical_subevent": "DISCLOSURE"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["prior"]["direction"] == "negative"
        assert body["ontology_id"] == "company_events.v1"


def test_get_collection_details_and_registry_backend() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.get("/v1/collections/acme")
        assert r.status_code == 200
        body = r.json()
        assert body["collection_name"] == "acme"
        assert body["ontology_id"] == "company_events.v1"
        assert body["ontology_version"] == "v1.0"
        assert body["registry_backend"] in {"memory", "neo4j"}


def test_get_or_create_collection_endpoint() -> None:
    with TestClient(app) as client:
        r1 = client.post(
            "/v1/collections/get-or-create",
            json={"collection_name": "acme", "ontology_id": "company_events.v1"},
        )
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["created"] is True
        assert b1["collection_name"] == "acme"
        assert b1["ontology_id"] == "company_events.v1"

        r2 = client.post(
            "/v1/collections/get-or-create",
            json={"collection_name": "acme", "ontology_id": "company_events.v1"},
        )
        assert r2.status_code == 200
        b2 = r2.json()
        assert b2["created"] is False

        r3 = client.post(
            "/v1/collections/get-or-create",
            json={"collection_name": "acme", "ontology_id": "economic_events.v1"},
        )
        assert r3.status_code == 409


def test_snapshot_search_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.get("/v1/collections/acme/snapshots/search", params={"q": "revenue"})
        assert r.status_code == 503


def test_chunk_timeline_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.get("/v1/collections/acme/chunks/c1/timeline")
        assert r.status_code == 503


def test_entity_collections_network_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        r = client.get("/v1/network/entities/HDFC%20Bank/collections")
        assert r.status_code == 503


def test_event_search_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.get("/v1/collections/acme/events/search")
        assert r.status_code == 503


def test_event_supersession_post_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.post(
            "/v1/collections/acme/events/supersession",
            json={"newer_event_id": "evt_a", "older_event_id": "evt_b"},
        )
        assert r.status_code == 503


def test_event_supersession_get_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.get("/v1/collections/acme/events/evt_x/supersession")
        assert r.status_code == 503


def test_rag_multi_step_requires_neo4j_when_disabled() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "acme", "ontology_id": "company_events.v1"})
        r = client.post(
            "/v1/collections/acme/rag/multi_step",
            json={"question": "What changed?", "max_steps": 3},
        )
        assert r.status_code == 503
