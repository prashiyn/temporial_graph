from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float | None:
    """Cosine similarity in [-1, 1], or None if lengths differ."""
    if len(a) != len(b) or not a:
        return None
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def to_float_list(raw: object) -> list[float] | None:
    if not isinstance(raw, list):
        return None
    out: list[float] = []
    for x in raw:
        if isinstance(x, bool):
            return None
        if isinstance(x, (int, float)):
            out.append(float(x))
        else:
            return None
    return out
