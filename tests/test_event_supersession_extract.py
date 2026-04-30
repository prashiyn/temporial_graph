from __future__ import annotations

from temporial_graph_rag.models.chunk import ChunkType, IngestChunk
from temporial_graph_rag.pipeline import processor as proc


def test_extract_events_passes_supersession_fields_from_events_list() -> None:
    chunk = IngestChunk(
        chunk_id="c1",
        content="x",
        type=ChunkType.TEXT,
        doc_id="d1",
        bundle_id="b1",
        page=1,
        section_title="",
        title_summary="",
        publish_date="2026-01-15",
        prev_chunk=None,
        next_chunk=None,
        canonical_event="LEGAL_REGULATORY",
        canonical_subevent="DISCLOSURE",
    )
    payload = {
        "events": [
            {
                "description": "a",
                "supersedes_event_id": " evt_old ",
                "invalidates_event_ids": ["evt_x", "", 99, "evt_y"],
                "disable_auto_supersedes": True,
            }
        ]
    }
    events = proc._extract_events(chunk, payload)
    assert len(events) == 1
    assert events[0]["supersedes_event_id"] == "evt_old"
    assert events[0]["invalidates_event_ids"] == ["evt_x", "evt_y"]
    assert events[0]["disable_auto_supersedes"] is True


def test_extract_events_root_payload_supersession_for_single_fallback() -> None:
    chunk = IngestChunk(
        chunk_id="c1",
        content="y",
        type=ChunkType.TEXT,
        doc_id="d1",
        bundle_id="b1",
        page=1,
        section_title="",
        title_summary="",
        publish_date="2026-02-01",
        prev_chunk=None,
        next_chunk=None,
        canonical_event="EARNINGS",
        canonical_subevent="GUIDANCE",
    )
    payload = {
        "description": "root",
        "supersedes_event_id": "prior",
        "invalidates_event_ids": ["a", "b"],
    }
    events = proc._extract_events(chunk, payload)
    assert len(events) == 1
    assert events[0]["supersedes_event_id"] == "prior"
    assert events[0]["invalidates_event_ids"] == ["a", "b"]
    assert events[0]["disable_auto_supersedes"] is False


def test_event_time_date_prefix() -> None:
    from temporial_graph_rag.graph.store import Neo4jGraphStore

    assert Neo4jGraphStore._event_time_date_prefix("2026-03-10T12:00:00Z") == "2026-03-10"
    assert Neo4jGraphStore._event_time_date_prefix("") == ""


def test_extract_events_stable_id_and_causes() -> None:
    chunk = IngestChunk(
        chunk_id="c1",
        content="x",
        type=ChunkType.TEXT,
        doc_id="d1",
        bundle_id="b1",
        page=1,
        section_title="",
        title_summary="",
        publish_date="2026-01-15",
        prev_chunk=None,
        next_chunk=None,
        canonical_event="LEGAL_REGULATORY",
        canonical_subevent="DISCLOSURE",
    )
    payload = {
        "events": [
            {
                "stable_event_id": " evt_stable ",
                "causes_event_ids": ["a", "", "b"],
                "causes": [
                    {"target_event_id": "x", "probability": 0.7, "reason": "r1"},
                    {"event_id": "y"},
                ],
                "description": "d",
            }
        ]
    }
    events = proc._extract_events(chunk, payload)
    assert len(events) == 1
    assert events[0]["stable_event_id"] == "evt_stable"
    assert events[0]["causes_event_ids"] == ["a", "b"]
    assert len(events[0]["causes"]) == 2
    assert events[0]["causes"][0]["target_event_id"] == "x"
    assert events[0]["causes"][0]["probability"] == 0.7
    assert events[0]["causes"][1]["target_event_id"] == "y"


def test_graph_event_id_uses_stable_or_hash() -> None:
    from temporial_graph_rag.graph.store import Neo4jGraphStore

    ev = {"stable_event_id": "my_stable", "canonical_event": "E", "canonical_subevent": "S", "event_time": "t"}
    assert Neo4jGraphStore.graph_event_id(ev, persisted_snapshot_id="snap1", idx=0, ingested_at="t") == "my_stable"
    ev2 = {"canonical_event": "E", "canonical_subevent": "S", "event_time": "2026-01-01T00:00:00Z"}
    gid = Neo4jGraphStore.graph_event_id(ev2, persisted_snapshot_id="snap1", idx=0, ingested_at="t")
    assert gid.startswith("evt_")
    assert len(gid) == 4 + 24
