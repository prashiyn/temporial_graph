from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from temporial_graph_rag.llm import LLMClient
from temporial_graph_rag.models.chunk import IngestChunk
from temporial_graph_rag.models.entity import EntityRecord
from temporial_graph_rag.ontology.loader import Ontology
from temporial_graph_rag.pipeline.scoring import (
    infer_causality_reason,
    score_impact,
    scoring_controls_from_env,
)


def _maybe_parse_json(content: str) -> Any:
    text = content.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_text": text}


def _entity_resolution_assist_enabled() -> bool:
    v = (os.getenv("ENTITY_RESOLUTION_ASSIST_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _entity_resolution_assist(
    llm: LLMClient,
    entities: list[dict[str, Any]],
    excerpt: str,
) -> list[dict[str, Any]]:
    """LLM pass to merge duplicate entity mentions (notebook EntityResolution spirit, Neo4j-targeted)."""
    if not entities:
        return entities
    payload = json.dumps({"entities": entities, "excerpt": excerpt[:6000]}, ensure_ascii=False)
    resp = llm.complete(
        task_name="entity_resolution_assist",
        messages=[
            {
                "role": "system",
                "content": (
                    "You normalize and deduplicate financial entity mentions for a temporal knowledge graph. "
                    "Merge obvious duplicates (e.g. company legal name vs ticker). "
                    "Return a single JSON object: {\"entities\": [ {...}, ... ]} using the same keys as the input "
                    "objects (name, entity_type, ticker, role, aliases, sector, industry, country, exchange, etc.). "
                    "Do not fabricate tickers or facts."
                ),
            },
            {"role": "user", "content": payload},
        ],
    )
    parsed = _maybe_parse_json(str(resp.get("content", "")))
    if not isinstance(parsed, dict):
        return entities
    out = parsed.get("entities")
    if not isinstance(out, list):
        return entities
    cleaned = [x for x in out if isinstance(x, dict) and str(x.get("name", "")).strip()]
    return cleaned if cleaned else entities


def _extract_entities(event_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = event_payload.get("entities", [])
    entities: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return entities
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        record = EntityRecord(
            id=str(item.get("id", "")).strip() or None,
            name=name,
            entity_type=str(item.get("entity_type", item.get("type", "Unknown"))),
            aliases=item.get("aliases", []) if isinstance(item.get("aliases"), list) else [],
            ticker=str(item.get("ticker", "")).strip() or None,
            sector=str(item.get("sector", "")).strip() or None,
            industry=str(item.get("industry", "")).strip() or None,
            country=str(item.get("country", "")).strip() or None,
            exchange=str(item.get("exchange", "")).strip() or None,
            role=str(item.get("role", item.get("relation", "mentioned"))).strip() or None,
            company=str(item.get("company", "")).strip() or None,
            start_date=str(item.get("start_date", "")).strip() or None,
            end_date=str(item.get("end_date", "")).strip() or None,
            institution_type=str(item.get("institution_type", item.get("type", ""))).strip() or None,
            category=str(item.get("category", "")).strip() or None,
        )
        entities.append(record.model_dump())
    return entities


def _parse_iso_or_default(value: str | None, fallback_date: str | None) -> str:
    candidate = (value or "").strip()
    if candidate:
        try:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return candidate
        except ValueError:
            pass
    if fallback_date:
        return f"{fallback_date}T00:00:00Z"
    return datetime.now(timezone.utc).isoformat()


def _coerce_event_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _coerce_causes_entries(value: Any) -> list[dict[str, Any]]:
    """Rich event→event causality from extraction: [{target_event_id, probability?, reason?}, ...]."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("target_event_id") or item.get("event_id") or "").strip()
        if not tid:
            continue
        prob = item.get("probability")
        p_float: float | None = None
        if isinstance(prob, (int, float)) and not isinstance(prob, bool):
            p_float = float(prob)
        reason = str(item.get("reason") or "").strip() or None
        out.append({"target_event_id": tid, "probability": p_float, "reason": reason})
    return out


def _extract_events(chunk: IngestChunk, event_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events_raw = event_payload.get("events")
    events: list[dict[str, Any]] = []
    if isinstance(events_raw, list):
        for i, e in enumerate(events_raw):
            if not isinstance(e, dict):
                continue
            supersedes = str(e.get("supersedes_event_id") or "").strip() or None
            invalidates = _coerce_event_id_list(e.get("invalidates_event_ids"))
            disable_auto = e.get("disable_auto_supersedes")
            stable = str(e.get("stable_event_id") or "").strip() or None
            causes_ids = _coerce_event_id_list(e.get("causes_event_ids"))
            causes_rich = _coerce_causes_entries(e.get("causes"))
            events.append(
                {
                    "event_id": str(e.get("event_id") or uuid.uuid4()),
                    "stable_event_id": stable,
                    "canonical_event": str(e.get("canonical_event") or chunk.canonical_event),
                    "canonical_subevent": str(e.get("canonical_subevent") or chunk.canonical_subevent),
                    "normalized_subtype": str(
                        e.get("normalized_subtype") or e.get("subtype") or chunk.canonical_subevent
                    ),
                    "event_time": _parse_iso_or_default(
                        str(e.get("event_time") or e.get("timestamp") or ""),
                        chunk.publish_date,
                    ),
                    "confidence": float(e.get("confidence", 0.6)),
                    "description": str(e.get("description") or event_payload.get("summary") or ""),
                    "supersedes_event_id": supersedes,
                    "invalidates_event_ids": invalidates,
                    "disable_auto_supersedes": bool(disable_auto) if disable_auto is not None else False,
                    "causes_event_ids": causes_ids,
                    "causes": causes_rich,
                }
            )
    if events:
        return events
    root_supersedes = str(event_payload.get("supersedes_event_id") or "").strip() or None
    root_invalidates = _coerce_event_id_list(event_payload.get("invalidates_event_ids"))
    root_disable_auto = event_payload.get("disable_auto_supersedes")
    root_stable = str(event_payload.get("stable_event_id") or "").strip() or None
    root_causes_ids = _coerce_event_id_list(event_payload.get("causes_event_ids"))
    root_causes = _coerce_causes_entries(event_payload.get("causes"))
    return [
        {
            "event_id": str(uuid.uuid4()),
            "stable_event_id": root_stable,
            "canonical_event": chunk.canonical_event,
            "canonical_subevent": chunk.canonical_subevent,
            "normalized_subtype": str(event_payload.get("normalized_subtype") or chunk.canonical_subevent),
            "event_time": _parse_iso_or_default(str(event_payload.get("event_time") or ""), chunk.publish_date),
            "confidence": float(event_payload.get("confidence", 0.6)),
            "description": str(event_payload.get("description") or ""),
            "supersedes_event_id": root_supersedes,
            "invalidates_event_ids": root_invalidates,
            "disable_auto_supersedes": bool(root_disable_auto) if root_disable_auto is not None else False,
            "causes_event_ids": root_causes_ids,
            "causes": root_causes,
        }
    ]


def _normalize_predicates(event_payload: dict[str, Any], ontology: Ontology | None) -> dict[str, Any]:
    if not isinstance(event_payload, dict):
        return event_payload
    if ontology is None:
        return event_payload

    triplets = event_payload.get("triplets")
    if not isinstance(triplets, list):
        return event_payload

    normalized_triplets: list[dict[str, Any]] = []
    for item in triplets:
        if not isinstance(item, dict):
            continue
        predicate = str(item.get("predicate", "")).upper().strip()
        if not predicate:
            predicate = "RELATES_TO"
        if not ontology.is_allowed_predicate(predicate):
            predicate = "RELATES_TO"
        normalized = dict(item)
        normalized["predicate"] = predicate
        normalized_triplets.append(normalized)

    normalized_payload = dict(event_payload)
    normalized_payload["triplets"] = normalized_triplets
    return normalized_payload


@dataclass(frozen=True)
class ProcessedChunk:
    chunk_id: str
    canonical_event: str
    canonical_subevent: str
    extraction_text: str
    statement_extraction: dict[str, Any]
    temporal_range_extraction: dict[str, Any]
    event_or_triplet_extraction: dict[str, Any]
    embedding_model: str | None
    embedding_vector_size: int | None
    impact_direction: str
    impact_magnitude: str
    impact_probability: float
    short_term_return_bps: int
    medium_term_return_bps: int
    decay_half_life_days: int
    causality_target: str
    causality_reason: str
    entities: list[dict[str, Any]]
    extracted_events: list[dict[str, Any]]
    embedding_vector: list[float] | None = None


class ChunkProcessor:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client
        self.blend_with_model, self.prior_weight = scoring_controls_from_env()

    def process_chunk(self, chunk: IngestChunk, *, ontology: Ontology | None = None) -> ProcessedChunk:
        text = chunk.extraction_text

        statement_resp = self.llm_client.complete(
            task_name="statement_extraction",
            messages=[
                {"role": "system", "content": "Extract atomic statements from chunk text."},
                {"role": "user", "content": text},
            ],
        )
        temporal_resp = self.llm_client.complete(
            task_name="temporal_range_extraction",
            messages=[
                {"role": "system", "content": "Extract temporal validity fields from text."},
                {"role": "user", "content": text},
            ],
        )
        event_resp = self.llm_client.complete(
            task_name="event_or_triplet_extraction",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract event/triplet output from text. "
                        "When emitting triplets, predicates must be from the allowed list.\n\n"
                        f"Allowed predicates:\n{ontology.predicate_definitions_text() if ontology else '- RELATES_TO'}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"canonical_event={chunk.canonical_event}\n"
                        f"canonical_subevent={chunk.canonical_subevent}\n\n"
                        f"{text}"
                    ),
                },
            ],
        )
        embedding_resp = self.llm_client.embeddings(
            task_name="embeddings",
            input_value=text,
            input_type="search_document",
        )
        embedding_data = embedding_resp.get("data") or []
        first_vector = embedding_data[0].get("embedding") if embedding_data else None
        vector_list: list[float] | None = None
        if isinstance(first_vector, list) and all(isinstance(x, (int, float)) for x in first_vector):
            vector_list = [float(x) for x in first_vector]
        vector_size = len(vector_list) if vector_list is not None else None
        event_payload = _maybe_parse_json(event_resp.get("content", ""))
        event_payload = _normalize_predicates(event_payload, ontology)
        impact = score_impact(
            chunk,
            ontology=ontology,
            event_or_triplet_extraction=event_payload,
            blend_with_model=self.blend_with_model,
            prior_weight=self.prior_weight,
        )

        entities = _extract_entities(event_payload)
        if _entity_resolution_assist_enabled() and entities:
            entities = _entity_resolution_assist(self.llm_client, entities, text)

        return ProcessedChunk(
            chunk_id=chunk.chunk_id,
            canonical_event=chunk.canonical_event,
            canonical_subevent=chunk.canonical_subevent,
            extraction_text=text,
            statement_extraction=_maybe_parse_json(statement_resp.get("content", "")),
            temporal_range_extraction=_maybe_parse_json(temporal_resp.get("content", "")),
            event_or_triplet_extraction=event_payload,
            embedding_model=embedding_resp.get("model"),
            embedding_vector_size=vector_size,
            embedding_vector=vector_list,
            impact_direction=impact.direction,
            impact_magnitude=impact.magnitude,
            impact_probability=impact.probability,
            short_term_return_bps=impact.short_term_return_bps,
            medium_term_return_bps=impact.medium_term_return_bps,
            decay_half_life_days=impact.decay_half_life_days,
            causality_target=f"{chunk.doc_id}:price",
            causality_reason=infer_causality_reason(chunk, impact.direction),
            entities=entities,
            extracted_events=_extract_events(chunk, event_payload),
        )
