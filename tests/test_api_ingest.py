from __future__ import annotations

import os

from fastapi.testclient import TestClient

from temporial_graph_rag.api.main import app, get_chunk_processor, registry
from temporial_graph_rag.pipeline.processor import ProcessedChunk


class FakeProcessor:
    def process_chunk(self, chunk, *, ontology=None):
        return ProcessedChunk(
            chunk_id=chunk.chunk_id,
            canonical_event=chunk.canonical_event,
            canonical_subevent=chunk.canonical_subevent,
            extraction_text=chunk.extraction_text,
            statement_extraction={},
            temporal_range_extraction={},
            event_or_triplet_extraction={},
            embedding_model="fake-embed-model",
            embedding_vector_size=3,
            impact_direction="positive",
            impact_magnitude="medium",
            impact_probability=0.8,
            short_term_return_bps=120,
            medium_term_return_bps=70,
            decay_half_life_days=30,
            causality_target=f"{chunk.doc_id}:price",
            causality_reason="heuristic test reason",
            entities=[
                {
                    "id": "inst_hdfc_bank",
                    "name": "HDFC Bank",
                    "entity_type": "Institution",
                    "institution_type": "Bank",
                    "category": "Lender",
                    "country": "IN",
                    "role": "banker",
                    "aliases": ["HDFC BK"],
                }
            ],
            extracted_events=[
                {
                    "event_id": "evt_fake",
                    "canonical_event": chunk.canonical_event,
                    "canonical_subevent": chunk.canonical_subevent,
                    "normalized_subtype": chunk.canonical_subevent,
                    "event_time": "2026-04-03T00:00:00Z",
                    "confidence": 0.9,
                    "description": "fake event",
                }
            ],
            embedding_vector=None,
        )


def setup_function() -> None:
    os.environ["NEO4J_ENABLED"] = "false"
    # Reset in-memory bindings between tests.
    registry.clear()
    app.dependency_overrides.clear()


def test_collection_binding_isolation() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "reliance_industries", "ontology_id": "company_events.v1"})
        client.post("/v1/collections", json={"collection_name": "icici_bank", "ontology_id": "company_events.v1"})

        bad = client.post(
            "/v1/ingest/chunks",
            json={
                "collection_name": "reliance_industries",
                "ontology_id": "economic_events.v1",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "content": "Result announced",
                        "type": "text",
                        "doc_id": "d1",
                        "bundle_id": "b1",
                        "title_summary": "Q4 result summary",
                        "canonical_event": "EARNINGS_FINANCIALS",
                        "canonical_subevent": "RESULTS",
                    }
                ],
            },
        )
        assert bad.status_code == 400


def test_per_chunk_ontology_validation() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "reliance_industries", "ontology_id": "company_events.v1"})

        response = client.post(
            "/v1/ingest/chunks",
            json={
                "collection_name": "reliance_industries",
                "ontology_id": "company_events.v1",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "content": "Result announced",
                        "type": "text",
                        "doc_id": "d1",
                        "bundle_id": "b1",
                        "title_summary": "Q4 result summary",
                        "canonical_event": "EARNINGS_FINANCIALS",
                        "canonical_subevent": "NOT_A_REAL_SUBEVENT",
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "Invalid canonical_subevent" in response.text


def test_ingest_and_process_uses_dependency_injected_processor() -> None:
    app.dependency_overrides[get_chunk_processor] = lambda: FakeProcessor()
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "reliance_industries", "ontology_id": "company_events.v1"})

        response = client.post(
            "/v1/ingest/chunks/process",
            json={
                "collection_name": "reliance_industries",
                "ontology_id": "company_events.v1",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "content": "table cell A1 B1",
                        "type": "table",
                        "doc_id": "d1",
                        "bundle_id": "b1",
                        "title_summary": "table summary",
                        "canonical_event": "EARNINGS_FINANCIALS",
                        "canonical_subevent": "RESULTS",
                    }
                ],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["accepted_chunks"] == 1
        assert payload["processed"][0]["embedding_model"] == "fake-embed-model"
        assert payload["processed"][0]["impact_direction"] == "positive"
        assert payload["processed"][0]["causality_target"] == "d1:price"
        assert payload["processed"][0]["entities"][0]["name"] == "HDFC Bank"
        assert payload["processed"][0]["extracted_events"][0]["event_id"] == "evt_fake"
        assert payload.get("persisted_snapshots") == 0
