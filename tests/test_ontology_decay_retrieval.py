from __future__ import annotations

from pathlib import Path

from temporial_graph_rag.ontology.loader import Ontology, load_ontology


def test_company_ontology_decay_threshold() -> None:
    root = Path(__file__).resolve().parents[1] / "ontologies"
    o = load_ontology(root, "company_events.v1")
    assert o.get_decay_weight_threshold("RESULTS") == 0.1


def test_subevent_decay_override() -> None:
    o = Ontology(
        ontology_id="x",
        ontology_version="1",
        events={"E": ["S1", "S2"]},
        impact_priors={},
        predicates={},
        snapshot_embedding_supersession={},
        decay_retrieval={
            "default": {"decay_weight_threshold": 0.1},
            "subevent_overrides": {"S1": {"decay_weight_threshold": 0.25}},
        },
    )
    assert o.get_decay_weight_threshold("S1") == 0.25
    assert o.get_decay_weight_threshold("S2") == 0.1


def test_invalid_decay_threshold_falls_back() -> None:
    o = Ontology(
        ontology_id="x",
        ontology_version="1",
        events={"E": ["S"]},
        impact_priors={},
        predicates={},
        snapshot_embedding_supersession={},
        decay_retrieval={"default": {"decay_weight_threshold": 2.0}},
    )
    assert o.get_decay_weight_threshold("S") == 0.1
