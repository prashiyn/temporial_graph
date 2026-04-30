from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from temporial_graph_rag.graph.publish_time import parse_publish_instant
from temporial_graph_rag.ontology.loader import Ontology

_DEFAULT_HALF_LIFE_DAYS = 14.0


def reference_instant_for_decay(
    publish_date: str | None,
    ingested_at: str | None,
) -> datetime | None:
    """Prefer document publish time; fall back to ingest time (UTC)."""
    return parse_publish_instant(
        str(publish_date).strip() if publish_date else None,
        str(ingested_at or "").strip(),
    )


def decay_weight(
    *,
    publish_date: str | None,
    ingested_at: str | None,
    half_life_days: float | None,
    now: datetime,
) -> float:
    """Weight in (0, 1]: 1.0 at reference time, halves every ``half_life_days``."""
    hl = float(half_life_days) if half_life_days is not None else _DEFAULT_HALF_LIFE_DAYS
    if hl <= 0:
        return 1.0
    ref = reference_instant_for_decay(publish_date, ingested_at)
    if ref is None:
        return 1.0
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    now_ = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now_ - ref).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / hl))


def enrich_snapshot_hits_with_decay(
    hits: list[dict[str, Any]],
    ontology: Ontology,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Add ``decay_weight`` and drop rows below ontology subevent threshold."""
    now_ = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for h in hits:
        sub = str(h.get("canonical_subevent") or "")
        th = ontology.get_decay_weight_threshold(sub)
        w = decay_weight(
            publish_date=str(h.get("publish_date") or "") or None,
            ingested_at=str(h.get("ingested_at") or "") or None,
            half_life_days=h.get("decay_half_life_days"),
            now=now_,
        )
        if w < th:
            continue
        row = dict(h)
        row["decay_weight"] = round(w, 6)
        row["decay_weight_threshold"] = th
        out.append(row)
    return out


def sort_snapshot_hits_by_decay_and_similarity(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Higher combined score first: decay_weight * similarity when similarity present."""

    def key(h: dict[str, Any]) -> tuple[float, float]:
        sim = h.get("similarity")
        dw = float(h.get("decay_weight") or 1.0)
        if isinstance(sim, (int, float)):
            return (dw * float(sim), dw)
        return (dw, 0.0)

    return sorted(hits, key=key, reverse=True)
