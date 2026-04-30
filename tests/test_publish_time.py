from __future__ import annotations

from datetime import datetime, timezone

from temporial_graph_rag.graph.publish_time import hours_apart_utc, parse_publish_instant


def test_parse_date_only() -> None:
    t = parse_publish_instant("2026-06-01", "")
    assert t == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_fallback_ingested() -> None:
    t = parse_publish_instant(None, "2026-03-15T14:30:00Z")
    assert t is not None
    assert t.tzinfo is not None


def test_hours_apart_same_calendar_day() -> None:
    a = parse_publish_instant("2026-01-10", "")
    b = parse_publish_instant("2026-01-10", "")
    assert a is not None and b is not None
    assert hours_apart_utc(a, b) == 0.0


def test_hours_across_days() -> None:
    a = parse_publish_instant("2026-01-10", "")
    b = parse_publish_instant("2026-01-11", "")
    assert a is not None and b is not None
    assert hours_apart_utc(a, b) == 24.0
