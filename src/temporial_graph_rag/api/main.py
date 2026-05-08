from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from neo4j.exceptions import Neo4jError
from pydantic import BaseModel, Field

from temporial_graph_rag.api.collection_name_middleware import CollectionNameExposeMiddleware
from temporial_graph_rag.collections.registry import (
    CollectionRegistry,
    MutableCollectionRegistry,
    Neo4jCollectionRegistry,
)
from temporial_graph_rag.graph import Neo4jGraphStore, Neo4jSettings
from temporial_graph_rag.llm import LLMClient, LLMServiceConfig
from temporial_graph_rag.models.ingest import (
    IngestBatchRequest,
    IngestBatchResponse,
    IngestProcessResponse,
    ProcessedChunkSummary,
)
from temporial_graph_rag.models.query import (
    ChunkTimelineItem,
    ChunkTimelineResponse,
    CreateEventSupersessionRequest,
    EntityCollectionConnection,
    EntityCollectionsResponse,
    EventSearchHit,
    EventSearchResponse,
    EventSupersessionCreatedResponse,
    EventSupersessionDetailResponse,
    ImpactPriorResponse,
    MultiStepRagRequest,
    MultiStepRagResponse,
    RagAnswerRequest,
    RagAnswerResponse,
    RagSourceRef,
    SnapshotSearchHit,
    SnapshotSearchResponse,
)
from temporial_graph_rag.ontology.loader import load_ontology
from temporial_graph_rag.pipeline import ChunkProcessor
from temporial_graph_rag.retrieval import decay as retrieval_decay
from temporial_graph_rag.retrieval.multi_step import MultiStepRetriever


logger = logging.getLogger(__name__)


class CreateCollectionRequest(BaseModel):
    collection_name: str = Field(..., min_length=1)
    ontology_id: str = Field(..., min_length=1)


class CollectionResponse(BaseModel):
    collection_name: str
    ontology_id: str


class CollectionDetailResponse(CollectionResponse):
    ontology_version: str | None = None
    registry_backend: str


class CollectionGetOrCreateResponse(CollectionDetailResponse):
    created: bool


REPO_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGIES_DIR = REPO_ROOT / "ontologies"


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")
    neo4j_settings = Neo4jSettings.from_env()
    if neo4j_settings.enabled:
        store = Neo4jGraphStore(neo4j_settings)
        app.state.neo4j_store = store
        registry.set_backend(Neo4jCollectionRegistry(store))
    else:
        app.state.neo4j_store = None
        registry.set_backend(CollectionRegistry())

    if os.getenv("LLM_STARTUP_MODELS_CHECK", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            cfg = LLMServiceConfig.from_env()
            llm_probe = LLMClient(cfg)
            try:
                llm_probe.models()
            finally:
                llm_probe.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM_STARTUP_MODELS_CHECK: GET /llm/models failed: %s", exc)

    yield
    store = getattr(app.state, "neo4j_store", None)
    if store is not None:
        store.close()


app = FastAPI(title="temporial-graph-rag", lifespan=lifespan)
app.add_middleware(CollectionNameExposeMiddleware)
registry = MutableCollectionRegistry(CollectionRegistry())


def get_neo4j_store(request: Request) -> Neo4jGraphStore | None:
    return getattr(request.app.state, "neo4j_store", None)


def get_chunk_processor() -> ChunkProcessor:
    config = LLMServiceConfig.from_env()
    client = LLMClient(config)
    return ChunkProcessor(client)


def get_llm_client() -> LLMClient:
    return LLMClient(LLMServiceConfig.from_env())


def require_neo4j_store(request: Request) -> Neo4jGraphStore:
    store = get_neo4j_store(request)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is disabled. Set NEO4J_ENABLED=true and configure NEO4J_* in .env.",
        )
    return store


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/health/llm")
async def llm_health(llm: LLMClient = Depends(get_llm_client)) -> dict[str, object]:
    """Diagnostic: reachability of llm-service ``GET /llm/models`` (plan §8.2)."""
    try:
        payload = llm.models()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {exc}") from exc
    return {"llm": "ok", "models_response": payload}


@app.get("/v1/health/neo4j")
async def neo4j_health(request: Request) -> dict[str, str]:
    store = get_neo4j_store(request)
    if store is None:
        return {"neo4j": "disabled"}
    try:
        store.ping()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Neo4j unavailable: {exc}") from exc
    return {"neo4j": "ok"}


@app.get("/v1/collections", response_model=list[CollectionResponse])
async def list_collections() -> list[CollectionResponse]:
    return [
        CollectionResponse(collection_name=b.collection_name, ontology_id=b.ontology_id)
        for b in registry.list_bindings()
    ]


@app.get("/v1/collections/{collection_name}", response_model=CollectionDetailResponse)
async def get_collection(collection_name: str) -> CollectionDetailResponse:
    binding = registry.get(collection_name)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    ontology_version: str | None = None
    try:
        ontology = load_ontology(ONTOLOGIES_DIR, binding.ontology_id)
        ontology_version = ontology.ontology_version
    except FileNotFoundError:
        ontology_version = None
    return CollectionDetailResponse(
        collection_name=binding.collection_name,
        ontology_id=binding.ontology_id,
        ontology_version=ontology_version,
        registry_backend=registry.backend_kind(),
    )


@app.get("/v1/collections/{collection_name}/impact-prior", response_model=ImpactPriorResponse)
async def impact_prior_preview(
    collection_name: str,
    canonical_event: str,
    canonical_subevent: str,
) -> ImpactPriorResponse:
    binding = registry.get(collection_name)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    try:
        ontology = load_ontology(ONTOLOGIES_DIR, binding.ontology_id)
        ontology.validate_pair(canonical_event, canonical_subevent)
        prior = ontology.get_impact_prior(canonical_event, canonical_subevent)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImpactPriorResponse(
        collection_name=collection_name,
        ontology_id=ontology.ontology_id,
        ontology_version=ontology.ontology_version,
        canonical_event=canonical_event,
        canonical_subevent=canonical_subevent,
        prior=prior,
    )


@app.get("/v1/collections/{collection_name}/snapshots/search", response_model=SnapshotSearchResponse)
async def search_snapshots(
    request: Request,
    collection_name: str,
    q: str,
    limit: int = 10,
    canonical_event: str | None = None,
    mode: Literal["lexical", "vector"] = "lexical",
    llm: LLMClient = Depends(get_llm_client),
) -> SnapshotSearchResponse:
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter q must not be empty")
    if registry.get(collection_name) is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    limit = min(max(limit, 1), 50)

    query_embedding: list[float] | None = None
    if mode == "vector":
        try:
            emb_resp = llm.embeddings(
                task_name="embeddings",
                input_value=q.strip(),
                input_type="search_query",
            )
            data = emb_resp.get("data") or []
            vec = data[0].get("embedding") if data else None
            if isinstance(vec, list) and vec and all(isinstance(x, (int, float)) for x in vec):
                query_embedding = [float(x) for x in vec]
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Embedding query failed: {exc}") from exc
        if not query_embedding:
            raise HTTPException(
                status_code=502,
                detail="LLM embeddings response did not include a numeric vector for the query.",
            )

    try:
        raw_hits = store.search_snapshots(
            collection_name=collection_name,
            query=q,
            limit=limit,
            canonical_event=canonical_event,
            query_embedding=query_embedding,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    hits = [SnapshotSearchHit(**h) for h in raw_hits]
    return SnapshotSearchResponse(
        collection_name=collection_name,
        query=q.strip(),
        mode=mode,
        hits=hits,
    )


@app.get("/v1/collections/{collection_name}/chunks/{chunk_id}/timeline", response_model=ChunkTimelineResponse)
async def chunk_timeline(
    request: Request,
    collection_name: str,
    chunk_id: str,
    limit: int = 50,
) -> ChunkTimelineResponse:
    if registry.get(collection_name) is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    limit = min(max(limit, 1), 200)
    try:
        raw_items = store.chunk_timeline(
            collection_name=collection_name,
            chunk_id=chunk_id,
            limit=limit,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    items = [ChunkTimelineItem(**r) for r in raw_items]
    return ChunkTimelineResponse(collection_name=collection_name, chunk_id=chunk_id, items=items)


@app.get("/v1/network/entities/{entity_name}/collections", response_model=EntityCollectionsResponse)
async def entity_collections_network(
    request: Request,
    entity_name: str,
    limit: int = 25,
) -> EntityCollectionsResponse:
    store = require_neo4j_store(request)
    limit = min(max(limit, 1), 100)
    try:
        rows = store.entity_collection_connections(entity_name=entity_name, limit=limit)
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    return EntityCollectionsResponse(
        entity_name=entity_name,
        connections=[EntityCollectionConnection(**r) for r in rows],
    )


@app.get("/v1/collections/{collection_name}/events/search", response_model=EventSearchResponse)
async def search_events(
    request: Request,
    collection_name: str,
    limit: int = 20,
    canonical_event: str | None = None,
    canonical_subevent: str | None = None,
    q: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    include_superseded: bool = False,
    exclude_decay_suppressed_snapshots: bool = True,
) -> EventSearchResponse:
    if registry.get(collection_name) is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    limit = min(max(limit, 1), 100)
    try:
        rows = store.search_events(
            collection_name=collection_name,
            limit=limit,
            canonical_event=canonical_event,
            canonical_subevent=canonical_subevent,
            query=q,
            start_time=start_time,
            end_time=end_time,
            include_superseded=include_superseded,
            exclude_decay_suppressed_snapshots=exclude_decay_suppressed_snapshots,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    return EventSearchResponse(
        collection_name=collection_name,
        hits=[EventSearchHit(**r) for r in rows],
    )


@app.post(
    "/v1/collections/{collection_name}/events/supersession",
    response_model=EventSupersessionCreatedResponse,
)
async def create_event_supersession(
    collection_name: str,
    body: CreateEventSupersessionRequest,
    request: Request,
) -> EventSupersessionCreatedResponse:
    if registry.get(collection_name) is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    if body.newer_event_id == body.older_event_id:
        raise HTTPException(status_code=400, detail="newer_event_id and older_event_id must differ")
    try:
        row = store.merge_event_supersession(
            collection_name=collection_name,
            newer_event_id=body.newer_event_id,
            older_event_id=body.older_event_id,
            reason=body.reason,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="One or both events were not found in this collection",
        )
    return EventSupersessionCreatedResponse(collection_name=collection_name, **row)


@app.get(
    "/v1/collections/{collection_name}/events/{event_id}/supersession",
    response_model=EventSupersessionDetailResponse,
)
async def get_event_supersession(
    collection_name: str,
    event_id: str,
    request: Request,
) -> EventSupersessionDetailResponse:
    if registry.get(collection_name) is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    try:
        detail = store.event_supersession_detail(collection_name=collection_name, event_id=event_id)
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found in this collection")
    return EventSupersessionDetailResponse(collection_name=collection_name, **detail)


@app.post("/v1/collections/{collection_name}/rag/answer", response_model=RagAnswerResponse)
async def rag_answer(
    collection_name: str,
    body: RagAnswerRequest,
    request: Request,
    llm: LLMClient = Depends(get_llm_client),
) -> RagAnswerResponse:
    binding = registry.get(collection_name)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    try:
        ontology = load_ontology(ONTOLOGIES_DIR, binding.ontology_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    query_embedding: list[float] | None = None
    if body.retrieval_mode == "vector":
        try:
            emb_resp = llm.embeddings(
                task_name="embeddings",
                input_value=body.question.strip(),
                input_type="search_query",
            )
            data = emb_resp.get("data") or []
            vec = data[0].get("embedding") if data else None
            if isinstance(vec, list) and vec and all(isinstance(x, (int, float)) for x in vec):
                query_embedding = [float(x) for x in vec]
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Embedding query failed: {exc}") from exc
        if not query_embedding:
            raise HTTPException(
                status_code=502,
                detail="LLM embeddings response did not include a numeric vector for the question.",
            )

    fetch_limit = min(max(body.top_k * 5, body.top_k), 60)
    try:
        raw_hits = store.search_snapshots(
            collection_name=collection_name,
            query=body.question,
            limit=fetch_limit,
            query_embedding=query_embedding,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=502, detail=f"Neo4j query failed: {exc}") from exc

    ranked = retrieval_decay.sort_snapshot_hits_by_decay_and_similarity(
        retrieval_decay.enrich_snapshot_hits_with_decay(raw_hits, ontology)
    )[: body.top_k]

    if not ranked:
        return RagAnswerResponse(
            collection_name=collection_name,
            question=body.question,
            answer="No chunk snapshots above the ontology decay threshold for this collection.",
            sources=[],
        )

    parts: list[str] = []
    for i, h in enumerate(ranked):
        text = (h.get("extraction_text") or "")[:2000]
        parts.append(
            f"[{i + 1}] snapshot_id={h.get('snapshot_id')} chunk_id={h.get('chunk_id')} "
            f"doc_id={h.get('doc_id')}\n{text}"
        )
    context = "\n\n".join(parts)
    try:
        resp = llm.complete(
            task_name="answer_synthesis",
            messages=[
                {
                    "role": "system",
                    "content": "Answer using only the provided context snippets. If insufficient, say so briefly.",
                },
                {
                    "role": "user",
                    "content": f"Question:\n{body.question}\n\nContext:\n{context}",
                },
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM answer failed: {exc}") from exc

    answer = str(resp.get("content", "")).strip()
    sources = [
        RagSourceRef(
            snapshot_id=h.get("snapshot_id"),
            chunk_id=h.get("chunk_id"),
            doc_id=h.get("doc_id"),
        )
        for h in ranked
    ]
    return RagAnswerResponse(
        collection_name=collection_name,
        question=body.question,
        answer=answer or "(empty model response)",
        sources=sources,
    )


@app.post(
    "/v1/collections/{collection_name}/rag/multi_step",
    response_model=MultiStepRagResponse,
)
async def rag_multi_step(
    collection_name: str,
    body: MultiStepRagRequest,
    request: Request,
    llm: LLMClient = Depends(get_llm_client),
) -> MultiStepRagResponse:
    binding = registry.get(collection_name)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' does not exist")
    store = require_neo4j_store(request)
    try:
        ontology = load_ontology(ONTOLOGIES_DIR, binding.ontology_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    retriever = MultiStepRetriever(
        llm=llm,
        store=store,
        ontology=ontology,
        collection_name=collection_name,
        max_steps=body.max_steps,
    )
    try:
        result = retriever.run(body.question)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Multi-step retrieval failed: {exc}") from exc
    return MultiStepRagResponse(
        collection_name=collection_name,
        question=body.question,
        initial_plan=result.initial_plan,
        answer=result.answer,
        steps=result.steps,
    )


@app.post("/v1/collections", response_model=CollectionResponse)
async def create_collection(body: CreateCollectionRequest) -> CollectionResponse:
    try:
        # Validate ontology exists at create time.
        load_ontology(ONTOLOGIES_DIR, body.ontology_id)
        created = registry.create(body.collection_name, body.ontology_id)
        return CollectionResponse(
            collection_name=created.collection_name,
            ontology_id=created.ontology_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/collections/get-or-create", response_model=CollectionGetOrCreateResponse)
async def get_or_create_collection(body: CreateCollectionRequest) -> CollectionGetOrCreateResponse:
    try:
        existing = registry.get(body.collection_name)
        if existing is not None:
            if existing.ontology_id != body.ontology_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Collection '{body.collection_name}' already exists with ontology "
                        f"'{existing.ontology_id}'"
                    ),
                )
            ontology = load_ontology(ONTOLOGIES_DIR, existing.ontology_id)
            return CollectionGetOrCreateResponse(
                collection_name=existing.collection_name,
                ontology_id=existing.ontology_id,
                ontology_version=ontology.ontology_version,
                registry_backend=registry.backend_kind(),
                created=False,
            )
        ontology = load_ontology(ONTOLOGIES_DIR, body.ontology_id)
        created = registry.create(body.collection_name, body.ontology_id)
        return CollectionGetOrCreateResponse(
            collection_name=created.collection_name,
            ontology_id=created.ontology_id,
            ontology_version=ontology.ontology_version,
            registry_backend=registry.backend_kind(),
            created=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/ingest/chunks", response_model=IngestBatchResponse)
async def ingest_chunks(body: IngestBatchRequest) -> IngestBatchResponse:
    try:
        registry.ensure_binding(body.collection_name, body.ontology_id)
        ontology = load_ontology(ONTOLOGIES_DIR, body.ontology_id)
        for chunk in body.chunks:
            ontology.validate_pair(chunk.canonical_event, chunk.canonical_subevent)
            _ = chunk.extraction_text
        return IngestBatchResponse(
            collection_name=body.collection_name,
            ontology_id=body.ontology_id,
            accepted_chunks=len(body.chunks),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/ingest/chunks/process", response_model=IngestProcessResponse)
async def ingest_and_process_chunks(
    request: Request,
    body: IngestBatchRequest,
    processor: ChunkProcessor = Depends(get_chunk_processor),
) -> IngestProcessResponse:
    try:
        registry.ensure_binding(body.collection_name, body.ontology_id)
        ontology = load_ontology(ONTOLOGIES_DIR, body.ontology_id)
        store = get_neo4j_store(request)
        persisted = 0

        processed: list[ProcessedChunkSummary] = []
        for chunk in body.chunks:
            ontology.validate_pair(chunk.canonical_event, chunk.canonical_subevent)
            result = processor.process_chunk(chunk, ontology=ontology)
            if store is not None:
                try:
                    store.persist_chunk_snapshot(
                        collection_name=body.collection_name,
                        ontology_id=ontology.ontology_id,
                        ontology_version=ontology.ontology_version,
                        chunk=chunk,
                        result=result,
                        snapshot_embed_publish_window_hours=ontology.get_snapshot_embedding_publish_window_hours(
                            chunk.canonical_event
                        ),
                    )
                except Neo4jError as exc:
                    raise HTTPException(status_code=502, detail=f"Neo4j write failed: {exc}") from exc
                persisted += 1
            processed.append(
                ProcessedChunkSummary(
                    chunk_id=result.chunk_id,
                    canonical_event=result.canonical_event,
                    canonical_subevent=result.canonical_subevent,
                    extraction_text=result.extraction_text,
                    embedding_model=result.embedding_model,
                    embedding_vector_size=result.embedding_vector_size,
                    impact_direction=result.impact_direction,
                    impact_magnitude=result.impact_magnitude,
                    impact_probability=result.impact_probability,
                    short_term_return_bps=result.short_term_return_bps,
                    medium_term_return_bps=result.medium_term_return_bps,
                    decay_half_life_days=result.decay_half_life_days,
                    causality_target=result.causality_target,
                    causality_reason=result.causality_reason,
                    entities=result.entities,
                    extracted_events=result.extracted_events,
                )
            )

        return IngestProcessResponse(
            collection_name=body.collection_name,
            ontology_id=body.ontology_id,
            accepted_chunks=len(body.chunks),
            processed=processed,
            persisted_snapshots=persisted,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
