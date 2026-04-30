from __future__ import annotations

from pathlib import Path

from temporial_graph_rag.ontology.loader import Ontology, load_ontology


def test_company_ontology_default_publish_window() -> None:
    root = Path(__file__).resolve().parents[1] / "ontologies"
    o = load_ontology(root, "company_events.v1")
    assert o.get_snapshot_embedding_publish_window_hours("EARNINGS_FINANCIALS") == 12.0
    assert o.get_snapshot_embedding_publish_window_hours("OTHER") == 12.0


def test_missing_snapshot_section_uses_twelve_hours() -> None:
    o = Ontology(
        ontology_id="x",
        ontology_version="1",
        events={"A": ["B"]},
        impact_priors={},
        predicates={},
        snapshot_embedding_supersession={},
        decay_retrieval={},
    )
    assert o.get_snapshot_embedding_publish_window_hours("A") == 12.0


def test_event_override_hours() -> None:
    o = Ontology(
        ontology_id="x",
        ontology_version="1",
        events={"E1": ["S"], "E2": ["S"]},
        impact_priors={},
        predicates={},
        snapshot_embedding_supersession={
            "default": {"publish_date_max_hours_apart": 12},
            "event_overrides": {"E1": {"publish_date_max_hours_apart": 48}},
        },
        decay_retrieval={},
    )
    assert o.get_snapshot_embedding_publish_window_hours("E1") == 48.0
    assert o.get_snapshot_embedding_publish_window_hours("E2") == 12.0


def test_invalid_override_falls_back() -> None:
    o = Ontology(
        ontology_id="x",
        ontology_version="1",
        events={"E": ["S"]},
        impact_priors={},
        predicates={},
        snapshot_embedding_supersession={
            "default": {"publish_date_max_hours_apart": "bad"},
            "event_overrides": {"E": {"publish_date_max_hours_apart": -5}},
        },
        decay_retrieval={},
    )
    assert o.get_snapshot_embedding_publish_window_hours("E") == 12.0
