"""Weekly job: mark ``ChunkIngestSnapshot`` nodes below ontology decay weight threshold.

Sets ``retrieval_decay_suppressed_at`` (append-friendly; does not delete history).
Run: ``uv run python -m temporial_graph_rag.jobs.decay_suppress_weekly``
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from temporial_graph_rag.graph import Neo4jGraphStore, Neo4jSettings
from temporial_graph_rag.ontology.loader import load_ontology
from temporial_graph_rag.retrieval.decay import decay_weight


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run(*, page_size: int = 500) -> int:
    load_dotenv(_repo_root() / ".env")
    settings = Neo4jSettings.from_env()
    if not settings.enabled:
        print("NEO4J_ENABLED is false; nothing to do.", file=sys.stderr)
        return 1
    ontologies_dir = _repo_root() / "ontologies"
    store = Neo4jGraphStore(settings)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    total_marked = 0
    try:
        cols = store.list_rag_collections()
        for col in cols:
            cname = str(col.get("collection_name") or "")
            oid = str(col.get("ontology_id") or "")
            if not cname or not oid:
                continue
            try:
                ontology = load_ontology(ontologies_dir, oid)
            except FileNotFoundError:
                print(f"skip collection={cname} ontology missing: {oid}", file=sys.stderr)
                continue
            skip = 0
            while True:
                rows = store.fetch_snapshots_for_decay_evaluation(
                    collection_name=cname,
                    skip=skip,
                    limit=page_size,
                )
                if not rows:
                    break
                for row in rows:
                    sid = str(row.get("snapshot_id") or "")
                    if not sid:
                        continue
                    sub = str(row.get("canonical_subevent") or "")
                    th = ontology.get_decay_weight_threshold(sub)
                    w = decay_weight(
                        publish_date=str(row.get("publish_date") or "") or None,
                        ingested_at=str(row.get("ingested_at") or "") or None,
                        half_life_days=row.get("decay_half_life_days"),
                        now=now,
                    )
                    if w < th:
                        store.mark_snapshot_decay_suppressed(
                            collection_name=cname,
                            snapshot_id=sid,
                            suppressed_at_iso=now_iso,
                        )
                        total_marked += 1
                if len(rows) < page_size:
                    break
                skip += page_size
    finally:
        store.close()
    print(f"marked {total_marked} snapshots with retrieval_decay_suppressed_at={now_iso}")
    return 0


def main() -> None:
    page = int(os.getenv("DECAY_JOB_PAGE_SIZE", "500"))
    raise SystemExit(run(page_size=max(1, min(page, 5000))))


if __name__ == "__main__":
    main()
