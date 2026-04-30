from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class EntityRecord(BaseModel):
    # Common identity
    id: str | None = None
    name: str = Field(..., min_length=1)
    entity_type: str = Field(default="Unknown")
    aliases: list[str] = []

    # Company-centric
    ticker: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    market_cap: float | None = None
    market_cap_bucket: str | None = None
    listing_date: str | None = None
    is_active: bool | None = None

    # Person-centric
    role: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    # Institution-centric
    institution_type: str | None = None
    category: str | None = None

    # Shared metadata
    source: str = "llm_extraction"
    version: str = "v1"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("entity_type", mode="before")
    @classmethod
    def normalize_entity_type(cls, value: str | None) -> str:
        v = (value or "Unknown").strip()
        if not v:
            return "Unknown"
        return v

