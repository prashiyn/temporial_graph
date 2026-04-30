from __future__ import annotations

import os
from dataclasses import dataclass

from temporial_graph_rag.models.chunk import IngestChunk
from temporial_graph_rag.ontology.loader import Ontology


@dataclass(frozen=True)
class ImpactScore:
    direction: str
    magnitude: str
    probability: float
    short_term_return_bps: int
    medium_term_return_bps: int
    decay_half_life_days: int


NEGATIVE_SUBEVENT_HINTS = {
    "RESIGN",
    "FIRE",
    "AUDITOR_RESIGN",
    "OPERATIONS_DISRUPTION",
    "CONTRACT_LOSS",
    "INVESTIGATION",
    "LITIGATION",
    "SUSPENSION",
    "DELISTING",
    "LIQUIDATION",
    "EXTINCTION",
    "CAPACITY_REDUCTION",
}

POSITIVE_SUBEVENT_HINTS = {
    "RESULTS",
    "EARNINGS",
    "CONTRACT_WIN",
    "CAPACITY_ADDITION",
    "PRODUCT_LAUNCH",
    "EXPANSION",
    "RATING_UPDATE",
    "BUYBACK",
    "DIVIDEND",
    "MERGER",
    "ACQUISITION",
}


def infer_causality_reason(chunk: IngestChunk, direction: str) -> str:
    return (
        f"Canonical subevent '{chunk.canonical_subevent}' under '{chunk.canonical_event}' "
        f"is heuristically mapped to '{direction}' market direction."
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def scoring_controls_from_env() -> tuple[bool, float]:
    blend_enabled = _env_bool("IMPACT_BLEND_WITH_MODEL", False)
    prior_weight = _env_float("IMPACT_PRIOR_WEIGHT", 0.7)
    if prior_weight < 0:
        prior_weight = 0.0
    if prior_weight > 1:
        prior_weight = 1.0
    return blend_enabled, prior_weight


def _direction_to_score(direction: str) -> float:
    d = direction.lower().strip()
    if d == "positive":
        return 1.0
    if d == "negative":
        return -1.0
    return 0.0


def _score_to_direction(score: float) -> str:
    if score > 0.25:
        return "positive"
    if score < -0.25:
        return "negative"
    return "neutral"


def _magnitude_from_score(score: float) -> str:
    abs_score = abs(score)
    if abs_score >= 0.66:
        return "high"
    if abs_score >= 0.33:
        return "medium"
    return "low"


def _heuristic_score(chunk: IngestChunk) -> ImpactScore:
    subevent = chunk.canonical_subevent.upper().strip()
    if subevent in NEGATIVE_SUBEVENT_HINTS:
        return ImpactScore("negative", "medium", 0.72, -120, -80, 30)
    if subevent in POSITIVE_SUBEVENT_HINTS:
        return ImpactScore("positive", "medium", 0.74, 110, 70, 30)
    return ImpactScore("neutral", "low", 0.55, 0, 0, 14)


def _prior_score(chunk: IngestChunk, ontology: Ontology | None) -> ImpactScore:
    if ontology is None:
        return _heuristic_score(chunk)
    prior = ontology.get_impact_prior(chunk.canonical_event, chunk.canonical_subevent)
    return ImpactScore(
        direction=str(prior.get("direction", "neutral")),
        magnitude=str(prior.get("magnitude", "low")),
        probability=float(prior.get("probability", 0.55)),
        short_term_return_bps=int(prior.get("short_term_return_bps", 0)),
        medium_term_return_bps=int(prior.get("medium_term_return_bps", 0)),
        decay_half_life_days=int(prior.get("decay_half_life_days", 14)),
    )


def _extract_model_signal(event_or_triplet_extraction: dict[str, object]) -> dict[str, object]:
    if not isinstance(event_or_triplet_extraction, dict):
        return {}
    impact = event_or_triplet_extraction.get("impact")
    if isinstance(impact, dict):
        return impact
    return event_or_triplet_extraction


def score_impact(
    chunk: IngestChunk,
    *,
    ontology: Ontology | None = None,
    event_or_triplet_extraction: dict[str, object] | None = None,
    blend_with_model: bool = False,
    prior_weight: float = 0.7,
) -> ImpactScore:
    prior = _prior_score(chunk, ontology)
    if not blend_with_model or not event_or_triplet_extraction:
        return prior

    model = _extract_model_signal(event_or_triplet_extraction)
    model_direction = str(model.get("direction", prior.direction))
    model_probability = float(model.get("probability", prior.probability))
    model_short_bps = int(model.get("short_term_return_bps", prior.short_term_return_bps))
    model_medium_bps = int(model.get("medium_term_return_bps", prior.medium_term_return_bps))
    model_decay = int(model.get("decay_half_life_days", prior.decay_half_life_days))

    model_weight = 1.0 - prior_weight
    blended_score = (
        (_direction_to_score(prior.direction) * prior_weight)
        + (_direction_to_score(model_direction) * model_weight)
    )

    return ImpactScore(
        direction=_score_to_direction(blended_score),
        magnitude=_magnitude_from_score(blended_score),
        probability=(prior.probability * prior_weight) + (model_probability * model_weight),
        short_term_return_bps=int((prior.short_term_return_bps * prior_weight) + (model_short_bps * model_weight)),
        medium_term_return_bps=int(
            (prior.medium_term_return_bps * prior_weight) + (model_medium_bps * model_weight)
        ),
        decay_half_life_days=int((prior.decay_half_life_days * prior_weight) + (model_decay * model_weight)),
    )
