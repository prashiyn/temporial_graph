"""Validate ontology JSON: JSON Schema (structure) + semantic rules (taxonomy consistency)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]
    Draft202012Validator = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ontology_schema_path() -> Path:
    return _repo_root() / "schemas" / "ontology.schema.json"


def _all_subevent_labels(canonical_events: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for subs in canonical_events.values():
        if isinstance(subs, list):
            for s in subs:
                if isinstance(s, str) and s.strip():
                    out.add(s.upper().strip())
    return out


def _all_event_labels(canonical_events: dict[str, Any]) -> set[str]:
    return {str(k).upper().strip() for k in canonical_events.keys() if str(k).strip()}


def semantic_validate(data: dict[str, Any]) -> list[str]:
    """Return human-readable errors; empty list means semantic checks passed."""
    errors: list[str] = []
    ce = data.get("canonical_events")
    if not isinstance(ce, dict) or not ce:
        return errors

    events = _all_event_labels(ce)
    subevents = _all_subevent_labels(ce)

    preds = data.get("predicate_definitions")
    if isinstance(preds, dict) and "RELATES_TO" not in preds:
        errors.append(
            "predicate_definitions should include RELATES_TO (fallback predicate used when extraction is unknown)."
        )

    ip = data.get("impact_priors")
    if isinstance(ip, dict):
        ev_o = ip.get("event_overrides")
        if isinstance(ev_o, dict):
            for k in ev_o.keys():
                ku = str(k).upper().strip()
                if ku not in events:
                    errors.append(
                        f"impact_priors.event_overrides has unknown canonical_event '{k}' "
                        f"(not a key in canonical_events)."
                    )
        sub_o = ip.get("subevent_overrides")
        if isinstance(sub_o, dict):
            for k in sub_o.keys():
                ku = str(k).upper().strip()
                if ku not in subevents:
                    errors.append(
                        f"impact_priors.subevent_overrides has unknown canonical_subevent '{k}' "
                        f"(not listed under any canonical_events array)."
                    )

    se = data.get("snapshot_embedding_supersession")
    if isinstance(se, dict):
        ev_o = se.get("event_overrides")
        if isinstance(ev_o, dict):
            for k in ev_o.keys():
                ku = str(k).upper().strip()
                if ku not in events:
                    errors.append(
                        f"snapshot_embedding_supersession.event_overrides has unknown canonical_event '{k}'."
                    )

    dr = data.get("decay_retrieval")
    if isinstance(dr, dict):
        sub_o = dr.get("subevent_overrides")
        if isinstance(sub_o, dict):
            for k in sub_o.keys():
                ku = str(k).upper().strip()
                if ku not in subevents:
                    errors.append(
                        f"decay_retrieval.subevent_overrides has unknown canonical_subevent '{k}' "
                        f"(not listed under any canonical_events array)."
                    )

    return errors


def schema_validate(data: dict[str, Any], *, schema: dict[str, Any] | None = None) -> list[str]:
    """Validate against JSON Schema; returns list of error messages."""
    if jsonschema is None or Draft202012Validator is None:
        raise RuntimeError(
            "jsonschema is required for schema validation. Install with: uv add jsonschema"
        ) from _IMPORT_ERROR
    schema = schema or json.loads(ontology_schema_path().read_text())
    validator = Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(data)]


def validate_ontology_data(
    data: dict[str, Any],
    *,
    run_schema: bool = True,
    run_semantic: bool = True,
) -> list[str]:
    """Combined validation; all messages returned (schema first, then semantic)."""
    out: list[str] = []
    if run_schema:
        out.extend(schema_validate(data))
    if run_semantic:
        out.extend(semantic_validate(data))
    return out


def validate_ontology_file(path: Path, *, run_schema: bool = True, run_semantic: bool = True) -> list[str]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        return ["Root JSON value must be an object"]
    return validate_ontology_data(raw, run_schema=run_schema, run_semantic=run_semantic)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m temporial_graph_rag.ontology.schema_validation <ontology.json> [...]", file=sys.stderr)
        return 2
    bad = 0
    for p in args:
        path = Path(p)
        if not path.is_file():
            print(f"Not a file: {path}", file=sys.stderr)
            bad = 1
            continue
        try:
            errs = validate_ontology_file(path)
        except RuntimeError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            bad = 1
            continue
        if errs:
            bad = 1
            print(f"{path}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"{path}: OK")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
