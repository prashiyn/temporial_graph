from __future__ import annotations

import os
from typing import Any, Protocol


class RetrievalSessionStore(Protocol):
    def get_transcript(self, session_id: str) -> str | None: ...
    def append_transcript(self, session_id: str, chunk: str) -> None: ...


class MemoryRetrievalSessionStore:
    """In-process store for optional multi-turn retrieval sessions (no Redis)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get_transcript(self, session_id: str) -> str | None:
        return self._data.get(session_id)

    def append_transcript(self, session_id: str, chunk: str) -> None:
        prev = self._data.get(session_id, "")
        self._data[session_id] = prev + chunk


class RedisRetrievalSessionStore:
    """Optional Redis-backed transcript continuation (install ``redis`` extra)."""

    def __init__(self, *, url: str, prefix: str = "tgrag:retrieval:") -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get_transcript(self, session_id: str) -> str | None:
        v = self._r.get(self._key(session_id))
        return str(v) if v is not None else None

    def append_transcript(self, session_id: str, chunk: str) -> None:
        self._r.append(self._key(session_id), chunk)


def session_store_from_env() -> MemoryRetrievalSessionStore | RedisRetrievalSessionStore | None:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        return RedisRetrievalSessionStore(url=url)
    except Exception:  # noqa: BLE001
        return None
