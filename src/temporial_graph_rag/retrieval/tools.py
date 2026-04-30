from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from temporial_graph_rag.graph.store import Neo4jGraphStore
from temporial_graph_rag.llm import LLMClient
from temporial_graph_rag.ontology.loader import Ontology
from temporial_graph_rag.retrieval import decay as decay_mod
from temporial_graph_rag.retrieval import prompts


@dataclass
class RetrievalToolContext:
    store: Neo4jGraphStore
    llm: LLMClient
    collection_name: str
    ontology: Ontology


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


class RetrievalTools:
    """Notebook-style tools backed by Neo4j + LLM embeddings."""

    def __init__(self, ctx: RetrievalToolContext) -> None:
        self._ctx = ctx

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "search_documents":
            return self.search_documents(**arguments)
        if name == "search_events":
            return self.search_events(**arguments)
        if name == "trend_analysis":
            return self.trend_analysis(**arguments)
        return _json_dumps({"error": f"unknown_tool: {name}"})

    def search_documents(
        self,
        *,
        query: str,
        mode: str = "lexical",
        limit: int = 8,
        canonical_event: str | None = None,
        publish_date_start: str | None = None,
        publish_date_end: str | None = None,
    ) -> str:
        q = (query or "").strip()
        if not q:
            return _json_dumps({"hits": [], "note": "empty query"})
        limit = max(1, min(int(limit), 30))
        mode_n = (mode or "lexical").strip().lower()
        emb: list[float] | None = None
        if mode_n == "vector":
            try:
                resp = self._ctx.llm.embeddings(
                    task_name="embeddings",
                    input_value=q,
                    input_type="search_query",
                )
                data = resp.get("data") or []
                vec = data[0].get("embedding") if data else None
                if isinstance(vec, list) and vec and all(isinstance(x, (int, float)) for x in vec):
                    emb = [float(x) for x in vec]
            except Exception as exc:  # noqa: BLE001
                return _json_dumps({"error": f"embedding_failed: {exc}"})
            if not emb:
                return _json_dumps({"error": "no_embedding_vector"})

        raw = self._ctx.store.search_snapshots(
            collection_name=self._ctx.collection_name,
            query=q,
            limit=limit,
            canonical_event=canonical_event,
            query_embedding=emb,
            publish_date_min=publish_date_start,
            publish_date_max=publish_date_end,
            exclude_decay_suppressed=True,
        )
        filtered = decay_mod.enrich_snapshot_hits_with_decay(raw, self._ctx.ontology)
        ranked = decay_mod.sort_snapshot_hits_by_decay_and_similarity(filtered)
        return _json_dumps({"hits": ranked, "mode": mode_n})

    def search_events(
        self,
        *,
        query: str | None = None,
        limit: int = 15,
        canonical_event: str | None = None,
        canonical_subevent: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> str:
        limit = max(1, min(int(limit), 50))
        rows = self._ctx.store.search_events(
            collection_name=self._ctx.collection_name,
            limit=limit,
            canonical_event=canonical_event,
            canonical_subevent=canonical_subevent,
            query=query,
            start_time=start_time,
            end_time=end_time,
            include_superseded=False,
            exclude_decay_suppressed_snapshots=True,
        )
        return _json_dumps({"events": rows})

    def trend_analysis(
        self,
        *,
        question: str,
        companies: list[str],
        topic_filter: list[str],
        start_date: str,
        end_date: str,
    ) -> str:
        """Notebook-style grid of document searches, then LLM synthesis."""
        companies = [str(c).strip() for c in (companies or []) if str(c).strip()]
        topics = [str(t).strip() for t in (topic_filter or []) if str(t).strip()]
        if not companies:
            companies = [""]
        if not topics:
            topics = [""]

        blocks: list[str] = []
        for c in companies:
            for t in topics:
                q = " ".join(x for x in [c, t] if x).strip() or question.strip()
                body = self.search_documents(
                    query=q,
                    mode="lexical",
                    limit=6,
                    publish_date_start=start_date,
                    publish_date_end=end_date,
                )
                header = f"=== {c or '(all)'} · {t or '(general)'} ==="
                blocks.append(f"{header}\n{body}")

        joined = "\n\n".join(blocks)
        try:
            syn = self._ctx.llm.complete(
                task_name="retrieval_trend_synthesis",
                messages=[
                    {"role": "system", "content": prompts.TREND_SYNTHESIS_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Date window: {start_date} .. {end_date}\nQuestion: {question}\n\nData:\n{joined}",
                    },
                ],
            )
            summary = str(syn.get("content", "")).strip()
        except Exception as exc:  # noqa: BLE001
            summary = f"(trend synthesis failed: {exc})\n\nRaw sections:\n{joined[:8000]}"
        return _json_dumps({"trend_summary": summary, "sections_character_count": len(joined)})
