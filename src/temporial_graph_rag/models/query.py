from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SnapshotSearchHit(BaseModel):
    snapshot_id: str | None = None
    chunk_id: str | None = None
    doc_id: str | None = None
    bundle_id: str | None = None
    canonical_event: str | None = None
    canonical_subevent: str | None = None
    ingested_at: str | None = None
    extraction_text: str = ""
    similarity: float | None = None


class SnapshotSearchResponse(BaseModel):
    collection_name: str
    query: str
    mode: Literal["lexical", "vector"] = "lexical"
    hits: list[SnapshotSearchHit]


class ChunkTimelineItem(BaseModel):
    snapshot_id: str | None = None
    chunk_id: str | None = None
    canonical_event: str | None = None
    canonical_subevent: str | None = None
    ingested_at: str | None = None
    supersedes_snapshot_id: str | None = None


class ChunkTimelineResponse(BaseModel):
    collection_name: str
    chunk_id: str
    items: list[ChunkTimelineItem]


class ImpactPriorResponse(BaseModel):
    collection_name: str
    ontology_id: str
    ontology_version: str
    canonical_event: str
    canonical_subevent: str
    prior: dict[str, Any]


class RagAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=30)
    retrieval_mode: Literal["lexical", "vector"] = "lexical"


class RagSourceRef(BaseModel):
    snapshot_id: str | None = None
    chunk_id: str | None = None
    doc_id: str | None = None


class RagAnswerResponse(BaseModel):
    collection_name: str
    question: str
    answer: str
    sources: list[RagSourceRef]


class MultiStepRagRequest(BaseModel):
    question: str = Field(..., min_length=1)
    max_steps: int = Field(default=10, ge=1, le=25)


class MultiStepRagResponse(BaseModel):
    collection_name: str
    question: str
    initial_plan: str
    answer: str
    steps: list[dict[str, Any]] = []


class EntityCollectionConnection(BaseModel):
    collection_name: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    observed_roles: list[str] = []
    mention_count: int = 0


class EntityCollectionsResponse(BaseModel):
    entity_name: str
    connections: list[EntityCollectionConnection]


class EventSearchHit(BaseModel):
    event_id: str
    collection_name: str
    canonical_event: str
    canonical_subevent: str
    normalized_subtype: str | None = None
    event_time: str | None = None
    confidence: float | None = None
    direction: str | None = None
    magnitude: str | None = None
    probability: float | None = None
    description: str | None = None
    source_snapshot_id: str | None = None
    superseded_by_event_id: str | None = None
    supersession_reason: str | None = None


class EventSearchResponse(BaseModel):
    collection_name: str
    hits: list[EventSearchHit]


class CreateEventSupersessionRequest(BaseModel):
    newer_event_id: str = Field(..., min_length=1)
    older_event_id: str = Field(..., min_length=1)
    reason: str | None = None


class EventSupersessionCreatedResponse(BaseModel):
    collection_name: str
    newer_event_id: str
    older_event_id: str
    reason: str | None = None
    created_at: str | None = None


class EventSupersessionDetailResponse(BaseModel):
    collection_name: str
    event_id: str
    superseded_by_event_ids: list[str] = []
    supersedes_event_ids: list[str] = []
