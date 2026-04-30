"""Plan §9–§10: collection isolation and extraction_text contract."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from temporial_graph_rag.api.main import app, get_llm_client, registry
from temporial_graph_rag.models.chunk import ChunkType, IngestChunk
from temporial_graph_rag.models.extraction_text import extraction_text_for_ingest


def setup_function() -> None:
    os.environ["NEO4J_ENABLED"] = "false"
    registry.clear()
    app.dependency_overrides.clear()


def test_extraction_text_text_and_table_merge_content_and_title() -> None:
    chunk = IngestChunk(
        chunk_id="c1",
        content="body",
        type=ChunkType.TEXT,
        doc_id="d1",
        bundle_id="b1",
        title_summary="head",
        canonical_event="EARNINGS_FINANCIALS",
        canonical_subevent="RESULTS",
    )
    assert extraction_text_for_ingest(chunk) == "body\n\nhead"


def test_extraction_text_image_uses_title_only() -> None:
    chunk = IngestChunk(
        chunk_id="c1",
        content="BASE64WOULDGOHERE",
        type=ChunkType.IMAGE,
        doc_id="d1",
        bundle_id="b1",
        title_summary="chart shows revenue up",
        canonical_event="EARNINGS_FINANCIALS",
        canonical_subevent="RESULTS",
    )
    assert extraction_text_for_ingest(chunk) == "chart shows revenue up"


def test_two_collections_same_ontology_remain_distinct_bindings() -> None:
    with TestClient(app) as client:
        client.post("/v1/collections", json={"collection_name": "fund_a", "ontology_id": "company_events.v1"})
        client.post("/v1/collections", json={"collection_name": "fund_b", "ontology_id": "company_events.v1"})
        rows = client.get("/v1/collections").json()
        names = {r["collection_name"] for r in rows}
        assert names == {"fund_a", "fund_b"}
        assert registry.get("fund_a") is not None
        assert registry.get("fund_b") is not None
        assert registry.get("fund_a").ontology_id == registry.get("fund_b").ontology_id == "company_events.v1"


def test_llm_health_uses_models_endpoint() -> None:
    class OkLLM:
        def models(self) -> dict[str, object]:
            return {"ok": True}

    app.dependency_overrides[get_llm_client] = lambda: OkLLM()
    with TestClient(app) as client:
        r = client.get("/v1/health/llm")
        assert r.status_code == 200
        body = r.json()
        assert body["llm"] == "ok"
        assert body["models_response"] == {"ok": True}
