from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class IngestChunk(BaseModel):
    chunk_id: str = Field(..., description="Stable chunk identifier")
    content: str = Field(..., description="Chunk text, table, or image description")
    type: ChunkType = Field(..., description="One of text, table, image")
    doc_id: str = Field(..., description="Document id")
    page: int | None = Field(None, description="Source page when available")
    bundle_id: str = Field(..., description="Semantic bundle id")
    section_title: str | None = Field(None, description="Nearest section heading")
    title_summary: str = Field("", description="LLM section summary")
    publish_date: str | None = Field(None, description="Document publish date if provided")
    prev_chunk: str | None = Field(None, description="Previous chunk id")
    next_chunk: str | None = Field(None, description="Next chunk id")
    canonical_event: str = Field(..., description="Top-level ontology event type")
    canonical_subevent: str = Field(..., description="Ontology subevent type")

    @field_validator("publish_date", mode="before")
    @classmethod
    def default_publish_date_to_utc_today(cls, value: str | None) -> str:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return datetime.now(timezone.utc).date().isoformat()
        return value

    @model_validator(mode="after")
    def enforce_content_rules(self) -> "IngestChunk":
        # Content can be base64 for images; extraction should use title_summary only.
        if self.type == ChunkType.IMAGE and self.title_summary.strip() == "":
            raise ValueError("title_summary is required for image chunks")
        return self

    @property
    def extraction_text(self) -> str:
        if self.type == ChunkType.IMAGE:
            return self.title_summary.strip()
        merged = "\n\n".join(p for p in [self.content.strip(), self.title_summary.strip()] if p)
        return merged
