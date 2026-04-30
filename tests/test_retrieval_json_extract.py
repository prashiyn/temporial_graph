from __future__ import annotations

import pytest

from temporial_graph_rag.retrieval.json_extract import extract_json_object


def test_extract_raw_object() -> None:
    d = extract_json_object('prefix {"action": "final", "answer": "ok"} suffix')
    assert d["action"] == "final"


def test_extract_fenced() -> None:
    d = extract_json_object('```json\n{"a": 1}\n```')
    assert d["a"] == 1


def test_extract_invalid() -> None:
    with pytest.raises(ValueError):
        extract_json_object("no json here")
