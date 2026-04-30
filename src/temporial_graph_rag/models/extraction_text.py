"""Extraction text rules (IMPLEMENTATION_PLAN §3.2).

The canonical implementation lives on :class:`~temporial_graph_rag.models.chunk.IngestChunk`
as the ``extraction_text`` property. This module exists so callers can import a single
helper without reaching into model internals.
"""

from __future__ import annotations

from temporial_graph_rag.models.chunk import IngestChunk


def extraction_text_for_ingest(chunk: IngestChunk) -> str:
    """Return the string passed to statement/event LLM and embedder for ``chunk``."""
    return chunk.extraction_text
