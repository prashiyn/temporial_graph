from __future__ import annotations

from datetime import datetime, timezone


def parse_publish_instant(publish_date: str | None, ingested_at_fallback: str) -> datetime | None:
    """UTC instant for temporal comparison: chunk publish_date (date or ISO) or ingested_at fallback."""
    raw = (publish_date or "").strip()
    if raw:
        try:
            if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
                day = raw[:10]
                return datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    fb = (ingested_at_fallback or "").strip()
    if not fb:
        return None
    try:
        dt = datetime.fromisoformat(fb.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def hours_apart_utc(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 3600.0
