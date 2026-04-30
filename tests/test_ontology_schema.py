from __future__ import annotations

import json
from pathlib import Path

import pytest

from temporial_graph_rag.ontology.schema_validation import (
    semantic_validate,
    validate_ontology_data,
    validate_ontology_file,
)


def _company_ontology_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ontologies" / "company_events.v1.json"


def test_company_events_v1_passes_combined_validation() -> None:
    errs = validate_ontology_file(_company_ontology_path())
    assert errs == []


def test_semantic_rejects_unknown_subevent_override() -> None:
    data = json.loads(_company_ontology_path().read_text())
    data["impact_priors"]["subevent_overrides"]["NOT_A_REAL_SUBEVENT"] = {"direction": "neutral"}
    errs = semantic_validate(data)
    assert any("NOT_A_REAL_SUBEVENT" in e for e in errs)


def test_semantic_rejects_unknown_event_override() -> None:
    data = json.loads(_company_ontology_path().read_text())
    data["impact_priors"]["event_overrides"]["FAKE_EVENT"] = {"probability": 0.5}
    errs = semantic_validate(data)
    assert any("FAKE_EVENT" in e for e in errs)


def test_schema_rejects_extra_top_level_key() -> None:
    data = json.loads(_company_ontology_path().read_text())
    data["unknown_section"] = {}
    errs = validate_ontology_data(data, run_semantic=False)
    assert errs


def test_schema_rejects_bad_decay_threshold() -> None:
    data = json.loads(_company_ontology_path().read_text())
    data.setdefault("decay_retrieval", {})["default"] = {"decay_weight_threshold": 1.5}
    errs = validate_ontology_data(data, run_semantic=False)
    assert errs
