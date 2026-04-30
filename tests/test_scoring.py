from __future__ import annotations

from pathlib import Path

from temporial_graph_rag.models.chunk import IngestChunk
from temporial_graph_rag.ontology.loader import load_ontology
from temporial_graph_rag.pipeline.scoring import score_impact

_ONTOLOGIES = Path(__file__).resolve().parents[1] / "ontologies"


def _chunk(**kwargs):
    base = {
        "chunk_id": "c1",
        "content": "quarterly results are strong",
        "type": "text",
        "doc_id": "d1",
        "bundle_id": "b1",
        "title_summary": "summary",
        "canonical_event": "EARNINGS_FINANCIALS",
        "canonical_subevent": "RESULTS",
    }
    base.update(kwargs)
    return IngestChunk(**base)


def test_score_impact_uses_ontology_prior() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    score = score_impact(_chunk(), ontology=ontology)
    assert score.direction == "positive"
    assert score.short_term_return_bps == 110


def test_score_impact_blends_with_model_signal() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    model_signal = {
        "impact": {
            "direction": "negative",
            "probability": 0.8,
            "short_term_return_bps": -150,
            "medium_term_return_bps": -90,
            "decay_half_life_days": 25,
        }
    }
    score = score_impact(
        _chunk(),
        ontology=ontology,
        event_or_triplet_extraction=model_signal,
        blend_with_model=True,
        prior_weight=0.4,
    )
    assert score.direction in {"negative", "neutral"}
    assert score.short_term_return_bps < 0


def test_event_level_prior_legal_regulatory() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    score = score_impact(
        _chunk(
            canonical_event="LEGAL_REGULATORY",
            canonical_subevent="DISCLOSURE",
        ),
        ontology=ontology,
    )
    assert score.direction == "negative"
    assert score.short_term_return_bps == -40


def test_event_level_merges_with_default_for_subevent_without_override() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    score = score_impact(
        _chunk(canonical_event="EARNINGS_FINANCIALS", canonical_subevent="DELAY"),
        ontology=ontology,
    )
    assert score.decay_half_life_days == 45
    assert score.probability == 0.62
    assert score.direction == "neutral"
