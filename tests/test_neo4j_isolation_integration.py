"""Neo4j integration tests: collection isolation, event CAUSES, TripletFact nodes.

Enable with a live database:
  NEO4J_INTEGRATION_TEST=1 NEO4J_ENABLED=true NEO4J_URI=... NEO4J_PASSWORD=...

Otherwise tests skip (default CI / no Docker).
"""

from __future__ import annotations

import os
import uuid

import pytest

from temporial_graph_rag.collection_naming import to_internal_collection_name
from temporial_graph_rag.graph import Neo4jGraphStore, Neo4jSettings
from temporial_graph_rag.models.chunk import ChunkType, IngestChunk
from temporial_graph_rag.pipeline.processor import ProcessedChunk


def _integration_on() -> bool:
    return os.getenv("NEO4J_INTEGRATION_TEST", "").strip().lower() in ("1", "true", "yes", "on")


@pytest.fixture(scope="module")
def neo4j_integration_store():
    if not _integration_on():
        pytest.skip("Set NEO4J_INTEGRATION_TEST=1 to run Neo4j integration tests")
    pwd = (os.getenv("NEO4J_PASSWORD") or "").strip()
    if not pwd:
        pytest.skip("NEO4J_PASSWORD required for integration tests")
    prev_en = os.environ.get("NEO4J_ENABLED")
    os.environ["NEO4J_ENABLED"] = "true"
    try:
        settings = Neo4jSettings.from_env()
        store = Neo4jGraphStore(settings)
    except Exception as exc:  # noqa: BLE001
        if prev_en is None:
            os.environ.pop("NEO4J_ENABLED", None)
        else:
            os.environ["NEO4J_ENABLED"] = prev_en
        pytest.skip(f"Neo4j not reachable: {exc}")

    yield store
    store.close()
    if prev_en is None:
        os.environ.pop("NEO4J_ENABLED", None)
    else:
        os.environ["NEO4J_ENABLED"] = prev_en


def _wipe_collection(store: Neo4jGraphStore, name: str) -> None:
    n = to_internal_collection_name(name)
    db = store._settings.database
    with store._driver.session(database=db) as session:
        session.run("MATCH (c:RagCollection {name: $n}) DETACH DELETE c", n=n).consume()
        session.run(
            "MATCH (x) WHERE x.collection_name = $n DETACH DELETE x",
            n=n,
        ).consume()


def _chunk(cid: str, doc: str) -> IngestChunk:
    return IngestChunk(
        chunk_id=cid,
        content="integration body",
        type=ChunkType.TEXT,
        doc_id=doc,
        bundle_id=f"b-{cid}",
        title_summary="",
        publish_date="2026-06-01",
        canonical_event="EARNINGS_FINANCIALS",
        canonical_subevent="RESULTS",
    )


def _processed(
    chunk: IngestChunk,
    *,
    extracted_events: list[dict],
    triplets: list[dict] | None = None,
) -> ProcessedChunk:
    et = triplets if triplets is not None else []
    return ProcessedChunk(
        chunk_id=chunk.chunk_id,
        canonical_event=chunk.canonical_event,
        canonical_subevent=chunk.canonical_subevent,
        extraction_text=chunk.extraction_text,
        statement_extraction={},
        temporal_range_extraction={},
        event_or_triplet_extraction={"triplets": et},
        embedding_model=None,
        embedding_vector_size=None,
        impact_direction="neutral",
        impact_magnitude="low",
        impact_probability=0.55,
        short_term_return_bps=0,
        medium_term_return_bps=0,
        decay_half_life_days=14,
        causality_target=f"{chunk.doc_id}:price",
        causality_reason="integration",
        entities=[],
        extracted_events=extracted_events,
        embedding_vector=None,
    )


def test_collection_isolation_snapshots(neo4j_integration_store: Neo4jGraphStore) -> None:
    store = neo4j_integration_store
    suffix = uuid.uuid4().hex[:8]
    col_a = f"__itest_iso_a_{suffix}__"
    col_b = f"__itest_iso_b_{suffix}__"
    try:
        for col in (col_a, col_b):
            _wipe_collection(store, col)

        chunk = _chunk("chunk_iso_1", "doc_iso")
        ev = [
            {
                "stable_event_id": f"evt_iso_{suffix}",
                "description": "e",
                "event_time": "2026-06-01T00:00:00Z",
            }
        ]
        pr = _processed(chunk, extracted_events=ev)

        store.persist_chunk_snapshot(
            collection_name=col_a,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=chunk,
            result=pr,
            snapshot_embed_publish_window_hours=12.0,
        )
        store.persist_chunk_snapshot(
            collection_name=col_b,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=chunk,
            result=pr,
            snapshot_embed_publish_window_hours=12.0,
        )

        db = store._settings.database
        ica = to_internal_collection_name(col_a)
        icb = to_internal_collection_name(col_b)
        with store._driver.session(database=db) as session:
            ca = session.run(
                "MATCH (s:ChunkIngestSnapshot {collection_name: $c}) RETURN count(s) AS n",
                c=ica,
            ).single()
            cb = session.run(
                "MATCH (s:ChunkIngestSnapshot {collection_name: $c}) RETURN count(s) AS n",
                c=icb,
            ).single()
            assert int(ca["n"]) >= 1
            assert int(cb["n"]) >= 1
            cross = session.run(
                """
                MATCH (a:ChunkIngestSnapshot {collection_name: $ca})
                MATCH (b:ChunkIngestSnapshot {collection_name: $cb})
                WHERE a.chunk_id = b.chunk_id
                RETURN count(*) AS n
                """,
                ca=ica,
                cb=icb,
            ).single()
            assert int(cross["n"]) == 0
    finally:
        _wipe_collection(store, col_a)
        _wipe_collection(store, col_b)


def test_event_causes_edge_between_events(neo4j_integration_store: Neo4jGraphStore) -> None:
    store = neo4j_integration_store
    suffix = uuid.uuid4().hex[:8]
    col = f"__itest_cause_{suffix}__"
    _wipe_collection(store, col)
    try:
        tgt_stable = f"cause_tgt_{suffix}"
        src_stable = f"cause_src_{suffix}"

        c1 = _chunk(f"c1_{suffix}", f"d1_{suffix}")
        r1 = _processed(
            c1,
            extracted_events=[
                {
                    "stable_event_id": tgt_stable,
                    "description": "target event",
                    "event_time": "2026-06-10T00:00:00Z",
                }
            ],
        )
        store.persist_chunk_snapshot(
            collection_name=col,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=c1,
            result=r1,
            snapshot_embed_publish_window_hours=12.0,
        )

        c2 = _chunk(f"c2_{suffix}", f"d2_{suffix}")
        r2 = _processed(
            c2,
            extracted_events=[
                {
                    "stable_event_id": src_stable,
                    "description": "source causes target",
                    "event_time": "2026-06-11T00:00:00Z",
                    "causes_event_ids": [tgt_stable],
                }
            ],
        )
        store.persist_chunk_snapshot(
            collection_name=col,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=c2,
            result=r2,
            snapshot_embed_publish_window_hours=12.0,
        )

        db = store._settings.database
        with store._driver.session(database=db) as session:
            row = session.run(
                """
                MATCH (src:Event {event_id: $src, collection_name: $c})-[r:CAUSES]->(tgt:Event {event_id: $tgt, collection_name: $c})
                RETURN r.probability AS p, r.reason AS reason
                """,
                src=src_stable,
                tgt=tgt_stable,
                c=to_internal_collection_name(col),
            ).single()
            assert row is not None
            assert float(row["p"]) > 0
            assert row["reason"]
    finally:
        _wipe_collection(store, col)


def test_triplet_facts_linked_from_snapshot(neo4j_integration_store: Neo4jGraphStore) -> None:
    store = neo4j_integration_store
    suffix = uuid.uuid4().hex[:8]
    col = f"__itest_tr_{suffix}__"
    _wipe_collection(store, col)
    try:
        c1 = _chunk(f"ct_{suffix}", f"dt_{suffix}")
        r1 = _processed(
            c1,
            extracted_events=[
                {
                    "stable_event_id": f"ev_tr_{suffix}",
                    "description": "e",
                    "event_time": "2026-06-01T00:00:00Z",
                }
            ],
            triplets=[{"subject": "Acme Corp", "predicate": "SECURED", "object": "Contract X"}],
        )
        sid = store.persist_chunk_snapshot(
            collection_name=col,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=c1,
            result=r1,
            snapshot_embed_publish_window_hours=12.0,
        )

        db = store._settings.database
        with store._driver.session(database=db) as session:
            row = session.run(
                """
                MATCH (snap:ChunkIngestSnapshot {snapshot_id: $sid})-[:ASSERTS_TRIPLET]->(tf:TripletFact)
                WHERE tf.subject = $subj AND tf.predicate = $pred AND tf.object = $obj
                RETURN tf.triplet_id AS tid
                """,
                sid=sid,
                subj="Acme Corp",
                pred="SECURED",
                obj="Contract X",
            ).single()
            assert row is not None
            assert str(row["tid"]).startswith("tr_")
    finally:
        _wipe_collection(store, col)


def test_causes_rich_list_with_probability(neo4j_integration_store: Neo4jGraphStore) -> None:
    store = neo4j_integration_store
    suffix = uuid.uuid4().hex[:8]
    col = f"__itest_cr_{suffix}__"
    _wipe_collection(store, col)
    try:
        tgt_stable = f"cr_tgt_{suffix}"
        src_stable = f"cr_src_{suffix}"
        c1 = _chunk(f"c1r_{suffix}", "d")
        store.persist_chunk_snapshot(
            collection_name=col,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=c1,
            result=_processed(
                c1,
                extracted_events=[
                    {
                        "stable_event_id": tgt_stable,
                        "description": "t",
                        "event_time": "2026-06-01T00:00:00Z",
                    }
                ],
            ),
            snapshot_embed_publish_window_hours=12.0,
        )
        c2 = _chunk(f"c2r_{suffix}", "d2")
        store.persist_chunk_snapshot(
            collection_name=col,
            ontology_id="company_events.v1",
            ontology_version="v1.0",
            chunk=c2,
            result=_processed(
                c2,
                extracted_events=[
                    {
                        "stable_event_id": src_stable,
                        "description": "srcdesc",
                        "event_time": "2026-06-02T00:00:00Z",
                        "causes": [
                            {
                                "target_event_id": tgt_stable,
                                "probability": 0.82,
                                "reason": "earnings revision",
                            }
                        ],
                    }
                ],
            ),
            snapshot_embed_publish_window_hours=12.0,
        )
        db = store._settings.database
        with store._driver.session(database=db) as session:
            row = session.run(
                """
                MATCH (src:Event {event_id: $src})-[r:CAUSES]->(tgt:Event {event_id: $tgt})
                WHERE src.collection_name = $c AND tgt.collection_name = $c
                RETURN r.probability AS p, r.reason AS reason
                """,
                src=src_stable,
                tgt=tgt_stable,
                c=to_internal_collection_name(col),
            ).single()
            assert row is not None
            assert abs(float(row["p"]) - 0.82) < 1e-6
            assert "earnings" in str(row["reason"]).lower()
    finally:
        _wipe_collection(store, col)
