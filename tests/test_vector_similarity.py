from __future__ import annotations

import math

from temporial_graph_rag.graph.vector_similarity import cosine_similarity, to_float_list


def test_cosine_similarity_orthogonal() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_parallel() -> None:
    s = cosine_similarity([3.0, 4.0], [6.0, 8.0])
    assert s is not None and math.isclose(s, 1.0, rel_tol=1e-9)


def test_cosine_similarity_length_mismatch() -> None:
    assert cosine_similarity([1.0], [1.0, 0.0]) is None


def test_to_float_list() -> None:
    assert to_float_list([1, 2.5, -3]) == [1.0, 2.5, -3.0]
    assert to_float_list("x") is None
    assert to_float_list([1, "a"]) is None
