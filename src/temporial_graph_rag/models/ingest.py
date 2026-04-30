from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .chunk import IngestChunk


class IngestBatchRequest(BaseModel):
    collection_name: str = Field(..., min_length=1)
    ontology_id: str = Field(..., min_length=1)
    chunks: list[IngestChunk] = Field(..., min_length=1)


class IngestBatchResponse(BaseModel):
    collection_name: str
    ontology_id: str
    accepted_chunks: int


class ProcessedChunkSummary(BaseModel):
    chunk_id: str
    canonical_event: str
    canonical_subevent: str
    extraction_text: str
    embedding_model: str | None = None
    embedding_vector_size: int | None = None
    impact_direction: str
    impact_magnitude: str
    impact_probability: float
    short_term_return_bps: int
    medium_term_return_bps: int
    decay_half_life_days: int
    causality_target: str
    causality_reason: str
    entities: list[dict[str, Any]] = []
    extracted_events: list[dict[str, object]] = []


class IngestProcessResponse(IngestBatchResponse):
    processed: list[ProcessedChunkSummary]
    persisted_snapshots: int = 0
