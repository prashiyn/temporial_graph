from __future__ import annotations

from pathlib import Path

from temporial_graph_rag.ontology.loader import load_ontology
from temporial_graph_rag.pipeline.processor import _normalize_predicates


_ONTOLOGIES = Path(__file__).resolve().parents[1] / "ontologies"
_NOTEBOOK_PREDICATES = {
    "IS_A",
    "HAS_A",
    "LOCATED_IN",
    "HOLDS_ROLE",
    "PRODUCES",
    "SELLS",
    "LAUNCHED",
    "DEVELOPED",
    "ADOPTED_BY",
    "INVESTS_IN",
    "COLLABORATES_WITH",
    "SUPPLIES",
    "HAS_REVENUE",
    "INCREASED",
    "DECREASED",
    "RESULTED_IN",
    "TARGETS",
    "PART_OF",
    "DISCONTINUED",
    "SECURED",
}


def test_ontology_exposes_configurable_predicates() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    names = set(ontology.predicate_names())
    assert _NOTEBOOK_PREDICATES.issubset(names)
    assert "RELATES_TO" in names
    assert ontology.is_allowed_predicate("supplies")


def test_unknown_predicates_are_normalized_to_relates_to() -> None:
    ontology = load_ontology(_ONTOLOGIES, "company_events.v1")
    payload = {
        "triplets": [
            {"subject": "EventA", "predicate": "SUPPLIES", "object": "CompanyX"},
            {"subject": "EventB", "predicate": "NOT_ALLOWED", "object": "CompanyY"},
            {"subject": "EventC", "object": "CompanyZ"},
        ]
    }
    normalized = _normalize_predicates(payload, ontology)
    triplets = normalized["triplets"]
    assert triplets[0]["predicate"] == "SUPPLIES"
    assert triplets[1]["predicate"] == "RELATES_TO"
    assert triplets[2]["predicate"] == "RELATES_TO"
