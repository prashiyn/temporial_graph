from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Ontology:
    ontology_id: str
    ontology_version: str
    events: dict[str, list[str]]
    impact_priors: dict[str, object]
    predicates: dict[str, str]
    snapshot_embedding_supersession: dict[str, Any]
    decay_retrieval: dict[str, Any]

    def validate_pair(self, canonical_event: str, canonical_subevent: str) -> None:
        allowed = self.events.get(canonical_event)
        if not allowed:
            raise ValueError(f"Invalid canonical_event: {canonical_event}")
        if canonical_subevent not in allowed:
            raise ValueError(
                f"Invalid canonical_subevent '{canonical_subevent}' for canonical_event '{canonical_event}'"
            )

    def get_impact_prior(self, canonical_event: str, canonical_subevent: str) -> dict[str, object]:
        """Merge impact priors: default → canonical_event override → subevent override."""
        priors = self.impact_priors or {}
        if not isinstance(priors, dict):
            return {}

        default_prior = priors.get("default")
        if not isinstance(default_prior, dict):
            default_prior = {}

        event_overrides = priors.get("event_overrides")
        if not isinstance(event_overrides, dict):
            event_overrides = {}
        event_key = canonical_event.upper().strip()
        event_override = event_overrides.get(event_key, {})
        if not isinstance(event_override, dict):
            event_override = {}

        subevent_overrides = priors.get("subevent_overrides")
        if not isinstance(subevent_overrides, dict):
            subevent_overrides = {}
        sub_key = canonical_subevent.upper().strip()
        sub_override = subevent_overrides.get(sub_key, {})
        if not isinstance(sub_override, dict):
            sub_override = {}

        return {**default_prior, **event_override, **sub_override}

    def predicate_names(self) -> list[str]:
        return sorted(self.predicates.keys())

    def predicate_definitions_text(self) -> str:
        if not self.predicates:
            return ""
        lines = [f"- {name}: {desc}" for name, desc in sorted(self.predicates.items())]
        return "\n".join(lines)

    def is_allowed_predicate(self, predicate: str) -> bool:
        return predicate.upper().strip() in self.predicates

    def get_snapshot_embedding_publish_window_hours(self, canonical_event: str) -> float:
        """Max |publish_time difference| (hours) for embedding-driven snapshot supersession.

        Reads ``snapshot_embedding_supersession`` from the ontology JSON. Missing sections
        or malformed values fall back to 12 hours so new ontologies stay valid.
        """
        default_hours = 12.0
        se = self.snapshot_embedding_supersession
        if isinstance(se, dict):
            dflt = se.get("default")
            if isinstance(dflt, dict) and "publish_date_max_hours_apart" in dflt:
                default_hours = _safe_positive_float(
                    dflt.get("publish_date_max_hours_apart"),
                    default_hours,
                )
            overrides = se.get("event_overrides")
            if isinstance(overrides, dict):
                key = canonical_event.upper().strip()
                ev = overrides.get(key)
                if isinstance(ev, dict) and "publish_date_max_hours_apart" in ev:
                    return _safe_positive_float(
                        ev.get("publish_date_max_hours_apart"),
                        default_hours,
                    )
        return default_hours

    def get_decay_weight_threshold(self, canonical_subevent: str) -> float:
        """Minimum decay weight [0,1] to retain content in retrieval; below is dropped/suppressed.

        Configured per ``canonical_subevent`` under ``decay_retrieval``; missing JSON uses 0.1.
        """
        default_t = 0.1
        dr = self.decay_retrieval
        if isinstance(dr, dict):
            dflt = dr.get("default")
            if isinstance(dflt, dict) and "decay_weight_threshold" in dflt:
                default_t = _safe_unit_interval(dflt.get("decay_weight_threshold"), default_t)
            overrides = dr.get("subevent_overrides")
            if isinstance(overrides, dict):
                sk = canonical_subevent.upper().strip()
                sub = overrides.get(sk)
                if isinstance(sub, dict) and "decay_weight_threshold" in sub:
                    return _safe_unit_interval(sub.get("decay_weight_threshold"), default_t)
        return default_t


def _safe_positive_float(value: object, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        x = float(value)
    except (TypeError, ValueError):
        return fallback
    if x <= 0 or x > 8760:
        return fallback
    return x


def _safe_unit_interval(value: object, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        x = float(value)
    except (TypeError, ValueError):
        return fallback
    if x <= 0.0 or x > 1.0:
        return fallback
    return x


def load_ontology(ontologies_dir: Path, ontology_id: str) -> Ontology:
    path = ontologies_dir / f"{ontology_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Ontology file not found: {path}")

    raw = json.loads(path.read_text())
    se = raw.get("snapshot_embedding_supersession")
    if not isinstance(se, dict):
        se = {}
    dr = raw.get("decay_retrieval")
    if not isinstance(dr, dict):
        dr = {}
    return Ontology(
        ontology_id=raw["ontology_id"],
        ontology_version=raw["ontology_version"],
        events=raw["canonical_events"],
        impact_priors=raw.get("impact_priors", {}),
        predicates=raw.get("predicate_definitions", {}),
        snapshot_embedding_supersession=se,
        decay_retrieval=dr,
    )
