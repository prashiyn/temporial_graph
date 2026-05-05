from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from temporial_graph_rag.collection_naming import to_external_collection_name, to_internal_collection_name
from temporial_graph_rag.graph.config import Neo4jSettings
from temporial_graph_rag.graph.publish_time import hours_apart_utc, parse_publish_instant
from temporial_graph_rag.graph.vector_similarity import cosine_similarity, to_float_list
from temporial_graph_rag.models.chunk import IngestChunk
from temporial_graph_rag.pipeline.processor import ProcessedChunk


class Neo4jGraphStore:
    """Append-only chunk ingest snapshots scoped by collection_name."""

    def __init__(self, settings: Neo4jSettings) -> None:
        self._settings = settings
        self._driver = GraphDatabase.driver(
            settings.uri,
            auth=(settings.user, settings.password),
            max_connection_pool_size=settings.max_connection_pool_size,
        )
        self._driver.verify_connectivity()

    def close(self) -> None:
        self._driver.close()

    @staticmethod
    def _json(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)

    @staticmethod
    def _collection_company_name(collection_name: str) -> str:
        # Derive display tokens from logical name (strip storage prefix first).
        logical = to_external_collection_name(collection_name)
        return " ".join(p.capitalize() for p in logical.replace("-", "_").split("_") if p)

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(value.lower().strip().split())

    @staticmethod
    def _event_time_date_prefix(event_time: str) -> str:
        s = (event_time or "").strip()
        if len(s) >= 10:
            return s[:10]
        return s

    @staticmethod
    def graph_event_id(
        ev: dict[str, Any],
        *,
        persisted_snapshot_id: str,
        idx: int,
        ingested_at: str,
    ) -> str:
        """Neo4j Event id: optional stable_event_id from extraction, else content-derived hash."""
        stable = str(ev.get("stable_event_id") or "").strip()
        if stable:
            return stable[:256]
        event_time = str(ev.get("event_time") or ingested_at)
        event_hash = hashlib.sha256(
            f"{persisted_snapshot_id}:{idx}:{ev.get('canonical_event')}:{ev.get('canonical_subevent')}:{event_time}".encode(
                "utf-8"
            )
        ).hexdigest()
        return f"evt_{event_hash[:24]}"

    @staticmethod
    def _entity_identity_key(entity: dict[str, Any]) -> str:
        entity_type = str(entity.get("entity_type", entity.get("type", "Unknown"))).strip() or "Unknown"
        ticker = str(entity.get("ticker", "")).strip().upper()
        if entity_type.lower() == "company" and ticker:
            return f"TICKER::{ticker}"
        name = str(entity.get("name", "")).strip()
        normalized = Neo4jGraphStore._norm(name) if name else "unknown"
        return f"{normalized}::{entity_type}"

    def persist_chunk_snapshot(
        self,
        *,
        collection_name: str,
        ontology_id: str,
        ontology_version: str,
        chunk: IngestChunk,
        result: ProcessedChunk,
        snapshot_embed_publish_window_hours: float | None = None,
    ) -> str:
        collection_name = to_internal_collection_name(collection_name)
        snapshot_id = str(uuid.uuid4())
        ingested_at = datetime.now(timezone.utc).isoformat()

        query = """
        MERGE (col:RagCollection {name: $collection_name})
        SET col.ontology_id = $ontology_id,
            col.ontology_version = $ontology_version

        MERGE (ref:ChunkRef {chunk_id: $chunk_id, collection_name: $collection_name})
        OPTIONAL MATCH (ref)<-[:OF_CHUNK]-(prev:ChunkIngestSnapshot)
        WITH col, ref, prev
        ORDER BY prev.ingested_at DESC
        WITH col, ref, head(collect(prev)) AS prev_latest

        CREATE (snap:ChunkIngestSnapshot {
          snapshot_id: $snapshot_id,
          chunk_id: $chunk_id,
          collection_name: $collection_name,
          ontology_id: $ontology_id,
          ontology_version: $ontology_version,
          ingested_at: $ingested_at,
          canonical_event: $canonical_event,
          canonical_subevent: $canonical_subevent,
          chunk_type: $chunk_type,
          doc_id: $doc_id,
          bundle_id: $bundle_id,
          page: $page,
          section_title: $section_title,
          title_summary: $title_summary,
          publish_date: $publish_date,
          prev_chunk: $prev_chunk,
          next_chunk: $next_chunk,
          extraction_text: $extraction_text,
          statement_extraction_json: $statement_json,
          temporal_range_extraction_json: $temporal_json,
          event_or_triplet_extraction_json: $event_json,
          embedding_model: $embedding_model,
          embedding_vector_size: $embedding_vector_size,
          impact_direction: $impact_direction,
          impact_magnitude: $impact_magnitude,
          impact_probability: $impact_probability,
          short_term_return_bps: $short_term_return_bps,
          medium_term_return_bps: $medium_term_return_bps,
          decay_half_life_days: $decay_half_life_days,
          causality_target: $causality_target,
          causality_reason: $causality_reason
        })
        CREATE (snap)-[:IN_COLLECTION]->(col)
        CREATE (snap)-[:OF_CHUNK]->(ref)
        FOREACH (_ IN CASE WHEN prev_latest IS NULL THEN [] ELSE [1] END |
          CREATE (snap)-[:SUPERSEDES {reason: "newer_ingest"}]->(prev_latest)
        )
        MERGE (impact:ImpactSignal {
          snapshot_id: $snapshot_id,
          collection_name: $collection_name
        })
        SET impact.direction = $impact_direction,
            impact.magnitude = $impact_magnitude,
            impact.probability = $impact_probability,
            impact.short_term_return_bps = $short_term_return_bps,
            impact.medium_term_return_bps = $medium_term_return_bps,
            impact.decay_half_life_days = $decay_half_life_days
        CREATE (snap)-[:HAS_IMPACT]->(impact)
        MERGE (target:MarketTarget {
          collection_name: $collection_name,
          key: $causality_target
        })
        CREATE (snap)-[:CAUSES {
          probability: $impact_probability,
          reason: $causality_reason
        }]->(target)
        RETURN snap.snapshot_id AS snapshot_id
        """

        params: dict[str, Any] = {
            "collection_name": collection_name,
            "ontology_id": ontology_id,
            "ontology_version": ontology_version,
            "chunk_id": chunk.chunk_id,
            "snapshot_id": snapshot_id,
            "ingested_at": ingested_at,
            "canonical_event": chunk.canonical_event,
            "canonical_subevent": chunk.canonical_subevent,
            "chunk_type": chunk.type.value,
            "doc_id": chunk.doc_id,
            "bundle_id": chunk.bundle_id,
            "page": chunk.page,
            "section_title": chunk.section_title,
            "title_summary": chunk.title_summary,
            "publish_date": chunk.publish_date,
            "prev_chunk": chunk.prev_chunk,
            "next_chunk": chunk.next_chunk,
            "extraction_text": result.extraction_text,
            "statement_json": self._json(result.statement_extraction),
            "temporal_json": self._json(result.temporal_range_extraction),
            "event_json": self._json(result.event_or_triplet_extraction),
            "embedding_model": result.embedding_model,
            "embedding_vector_size": result.embedding_vector_size,
            "impact_direction": result.impact_direction,
            "impact_magnitude": result.impact_magnitude,
            "impact_probability": result.impact_probability,
            "short_term_return_bps": result.short_term_return_bps,
            "medium_term_return_bps": result.medium_term_return_bps,
            "decay_half_life_days": result.decay_half_life_days,
            "causality_target": result.causality_target,
            "causality_reason": result.causality_reason,
        }

        with self._driver.session(database=self._settings.database) as session:
            record = session.run(query, **params).single()
            if record is None:
                raise RuntimeError("Neo4j persist returned no record")
            persisted_snapshot_id = str(record["snapshot_id"])

            if self._settings.store_embeddings and result.embedding_vector:
                session.run(
                    """
                    MATCH (s:ChunkIngestSnapshot {snapshot_id: $snapshot_id, collection_name: $collection_name})
                    SET s.embedding = $embedding
                    """,
                    snapshot_id=persisted_snapshot_id,
                    collection_name=collection_name,
                    embedding=result.embedding_vector,
                ).consume()

            window_h = snapshot_embed_publish_window_hours
            if window_h is None:
                window_h = 12.0
            if (
                self._settings.snapshot_embed_supersession_enabled
                and self._settings.store_embeddings
                and result.embedding_vector
            ):
                self._apply_snapshot_embedding_supersession(
                    session,
                    collection_name=collection_name,
                    new_snapshot_id=persisted_snapshot_id,
                    new_chunk_id=chunk.chunk_id,
                    new_canonical_event=chunk.canonical_event,
                    new_publish_date=chunk.publish_date,
                    new_ingested_at=ingested_at,
                    new_embedding=result.embedding_vector,
                    publish_window_hours=window_h,
                )

            # Build entity layer for cross-collection aggregation while retaining collection scoping.
            focal_company = self._collection_company_name(collection_name)
            focal_norm = self._norm(focal_company)
            session.run(
                """
                MERGE (ge:GlobalEntity {normalized_name: $normalized_name, entity_type: "Company"})
                SET ge.display_name = $display_name
                MERGE (ce:CollectionEntity {
                  collection_name: $collection_name,
                  entity_key: $entity_key
                })
                SET ce.display_name = $display_name,
                    ce.entity_type = "Company"
                MERGE (ce)-[:REFERS_TO]->(ge)
                """,
                normalized_name=focal_norm,
                display_name=focal_company,
                collection_name=collection_name,
                entity_key=f"{focal_norm}::Company",
            ).consume()

            for ent in result.entities:
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                entity_type = (ent.get("entity_type") or ent.get("type") or "Unknown").strip() or "Unknown"
                role = (ent.get("role") or "mentioned").strip() or "mentioned"
                norm = self._norm(name)
                entity_key = self._entity_identity_key(ent)
                ticker = str(ent.get("ticker") or "").strip() or None
                sector = str(ent.get("sector") or "").strip() or None
                industry = str(ent.get("industry") or "").strip() or None
                country = str(ent.get("country") or "").strip() or None
                exchange = str(ent.get("exchange") or "").strip() or None
                aliases = ent.get("aliases", [])
                aliases_json = self._json(aliases if isinstance(aliases, list) else [])
                institution_type = str(ent.get("institution_type") or "").strip() or None
                category = str(ent.get("category") or "").strip() or None
                session.run(
                    """
                    MATCH (snap:ChunkIngestSnapshot {snapshot_id: $snapshot_id, collection_name: $collection_name})
                    MATCH (focal:CollectionEntity {collection_name: $collection_name, entity_key: $focal_entity_key})
                    MERGE (ge:GlobalEntity {normalized_name: $normalized_name, entity_type: $entity_type})
                    SET ge.display_name = $display_name
                    SET ge.ticker = coalesce($ticker, ge.ticker),
                        ge.sector = coalesce($sector, ge.sector),
                        ge.industry = coalesce($industry, ge.industry),
                        ge.country = coalesce($country, ge.country),
                        ge.exchange = coalesce($exchange, ge.exchange),
                        ge.aliases_json = $aliases_json,
                        ge.institution_type = coalesce($institution_type, ge.institution_type),
                        ge.category = coalesce($category, ge.category)
                    MERGE (ce:CollectionEntity {collection_name: $collection_name, entity_key: $entity_key})
                    SET ce.display_name = $display_name,
                        ce.entity_type = $entity_type,
                        ce.ticker = coalesce($ticker, ce.ticker),
                        ce.sector = coalesce($sector, ce.sector),
                        ce.industry = coalesce($industry, ce.industry),
                        ce.country = coalesce($country, ce.country),
                        ce.exchange = coalesce($exchange, ce.exchange),
                        ce.aliases_json = $aliases_json,
                        ce.institution_type = coalesce($institution_type, ce.institution_type),
                        ce.category = coalesce($category, ce.category)
                    MERGE (ce)-[:REFERS_TO]->(ge)
                    MERGE (snap)-[:INVOLVES {role: $role}]->(ce)
                    MERGE (focal)-[:BUSINESS_RELATION {kind: $role}]->(ce)
                    FOREACH (_ IN CASE WHEN $sector IS NULL THEN [] ELSE [1] END |
                      MERGE (s:GlobalSector {name: $sector})
                      MERGE (ge)-[:IN_SECTOR]->(s)
                    )
                    FOREACH (_ IN CASE WHEN $industry IS NULL THEN [] ELSE [1] END |
                      MERGE (i:GlobalIndustry {name: $industry})
                      MERGE (ge)-[:IN_INDUSTRY]->(i)
                    )
                    """,
                    snapshot_id=persisted_snapshot_id,
                    collection_name=collection_name,
                    focal_entity_key=f"{focal_norm}::Company",
                    normalized_name=norm,
                    entity_type=entity_type,
                    display_name=name,
                    entity_key=entity_key,
                    role=role.lower(),
                    ticker=ticker,
                    sector=sector,
                    industry=industry,
                    country=country,
                    exchange=exchange,
                    aliases_json=aliases_json,
                    institution_type=institution_type,
                    category=category,
                ).consume()

            for idx, ev in enumerate(result.extracted_events):
                event_time = str(ev.get("event_time") or ingested_at)
                event_id = self.graph_event_id(
                    ev,
                    persisted_snapshot_id=persisted_snapshot_id,
                    idx=idx,
                    ingested_at=ingested_at,
                )
                session.run(
                    """
                    MATCH (snap:ChunkIngestSnapshot {snapshot_id: $snapshot_id, collection_name: $collection_name})
                    MATCH (impact:ImpactSignal {snapshot_id: $snapshot_id, collection_name: $collection_name})
                    CREATE (ev:Event {
                      event_id: $event_id,
                      collection_name: $collection_name,
                      ontology_id: $ontology_id,
                      ontology_version: $ontology_version,
                      canonical_event: $canonical_event,
                      canonical_subevent: $canonical_subevent,
                      normalized_subtype: $normalized_subtype,
                      event_time: $event_time,
                      confidence: $confidence,
                      direction: $direction,
                      magnitude: $magnitude,
                      probability: $probability,
                      description: $description,
                      source_snapshot_id: $snapshot_id,
                      created_at: $created_at
                    })
                    CREATE (ev)-[:DERIVED_FROM]->(snap)
                    CREATE (ev)-[:HAS_IMPACT]->(impact)
                    WITH ev
                    MATCH (ce:CollectionEntity)<-[:INVOLVES]-(snap:ChunkIngestSnapshot {snapshot_id: $snapshot_id, collection_name: $collection_name})
                    MERGE (ev)-[:INVOLVES]->(ce)
                    """,
                    snapshot_id=persisted_snapshot_id,
                    collection_name=collection_name,
                    event_id=event_id,
                    ontology_id=ontology_id,
                    ontology_version=ontology_version,
                    canonical_event=str(ev.get("canonical_event") or chunk.canonical_event),
                    canonical_subevent=str(ev.get("canonical_subevent") or chunk.canonical_subevent),
                    normalized_subtype=str(ev.get("normalized_subtype") or chunk.canonical_subevent),
                    event_time=event_time,
                    confidence=float(ev.get("confidence", 0.6)),
                    direction=result.impact_direction,
                    magnitude=result.impact_magnitude,
                    probability=result.impact_probability,
                    description=str(ev.get("description") or ""),
                    created_at=ingested_at,
                ).consume()
                self._apply_event_supersession(
                    session,
                    collection_name=collection_name,
                    new_event_id=event_id,
                    ev=ev,
                    snapshot_id=persisted_snapshot_id,
                    ingested_at=ingested_at,
                )

            for idx, ev in enumerate(result.extracted_events):
                src_id = self.graph_event_id(
                    ev,
                    persisted_snapshot_id=persisted_snapshot_id,
                    idx=idx,
                    ingested_at=ingested_at,
                )
                self._apply_event_causes(
                    session,
                    collection_name=collection_name,
                    source_event_id=src_id,
                    ev=ev,
                    ingested_at=ingested_at,
                )

            self._persist_triplet_facts(
                session,
                collection_name=collection_name,
                snapshot_id=persisted_snapshot_id,
                ingested_at=ingested_at,
                ontology_id=ontology_id,
                triplets=result.event_or_triplet_extraction.get("triplets"),
            )

            return persisted_snapshot_id

    def _merge_snapshot_supersession_rel(
        self,
        session: Any,
        *,
        collection_name: str,
        newer_snapshot_id: str,
        older_snapshot_id: str,
        reason: str,
        edge_created_at: str,
        meta: dict[str, Any],
    ) -> None:
        session.run(
            """
            MATCH (new:ChunkIngestSnapshot {snapshot_id: $nid, collection_name: $c})
            MATCH (old:ChunkIngestSnapshot {snapshot_id: $oid, collection_name: $c})
            MERGE (new)-[s:SUPERSEDES]->(old)
            ON CREATE SET s.reason = $reason,
                          s.created_at = $edge_created_at,
                          s.meta_json = $meta_json
            """,
            nid=newer_snapshot_id,
            oid=older_snapshot_id,
            c=collection_name,
            reason=reason,
            edge_created_at=edge_created_at,
            meta_json=self._json(meta),
        ).consume()

    def _apply_snapshot_embedding_supersession(
        self,
        session: Any,
        *,
        collection_name: str,
        new_snapshot_id: str,
        new_chunk_id: str,
        new_canonical_event: str,
        new_publish_date: str | None,
        new_ingested_at: str,
        new_embedding: list[float],
        publish_window_hours: float,
    ) -> None:
        min_cos = max(0.0, min(1.0, float(self._settings.snapshot_embed_supersede_min_cosine)))
        max_targets = max(1, min(50, int(self._settings.snapshot_embed_supersede_max_targets)))

        new_t = parse_publish_instant(new_publish_date, new_ingested_at)
        if new_t is None:
            return

        cypher = """
        MATCH (old:ChunkIngestSnapshot {collection_name: $c})
        WHERE old.snapshot_id <> $new_sid
          AND old.canonical_event = $ce
          AND old.embedding IS NOT NULL
          AND old.ingested_at < $new_ingested_at
        """
        params: dict[str, Any] = {
            "c": collection_name,
            "new_sid": new_snapshot_id,
            "ce": new_canonical_event,
            "new_ingested_at": new_ingested_at,
        }
        if self._settings.snapshot_embed_supersede_same_chunk_only:
            cypher += " AND old.chunk_id = $chunk_id\n"
            params["chunk_id"] = new_chunk_id
        cypher += " RETURN old LIMIT 500\n"

        scored: list[tuple[float, str, float]] = []
        for record in session.run(cypher, **params):
            node = record["old"]
            props = {k: node[k] for k in node.keys()}
            old_pub = props.get("publish_date")
            old_ing = str(props.get("ingested_at") or "")
            old_t = parse_publish_instant(
                str(old_pub) if old_pub is not None else None,
                old_ing,
            )
            if old_t is None:
                continue
            hours_delta = hours_apart_utc(new_t, old_t)
            if hours_delta > publish_window_hours:
                continue
            emb = to_float_list(props.get("embedding"))
            if emb is None:
                continue
            sim = cosine_similarity(new_embedding, emb)
            if sim is None or sim < min_cos:
                continue
            old_sid = str(props.get("snapshot_id") or "")
            if not old_sid:
                continue
            scored.append((float(sim), old_sid, hours_delta))

        scored.sort(key=lambda t: t[0], reverse=True)
        for sim, old_sid, hours_delta in scored[:max_targets]:
            self._merge_snapshot_supersession_rel(
                session,
                collection_name=collection_name,
                newer_snapshot_id=new_snapshot_id,
                older_snapshot_id=old_sid,
                reason="embedding_similarity_publish_window",
                edge_created_at=new_ingested_at,
                meta={
                    "cosine_similarity": round(sim, 6),
                    "publish_hours_delta": round(hours_delta, 4),
                    "publish_window_hours": publish_window_hours,
                },
            )

    def _merge_event_supersedes(
        self,
        session: Any,
        *,
        collection_name: str,
        newer_event_id: str,
        older_event_id: str,
        reason: str,
        edge_created_at: str,
    ) -> bool:
        if newer_event_id == older_event_id:
            return False
        rec = session.run(
            """
            MATCH (new:Event {event_id: $newer_id, collection_name: $collection_name})
            MATCH (old:Event {event_id: $older_id, collection_name: $collection_name})
            MERGE (new)-[s:SUPERSEDES]->(old)
            ON CREATE SET s.reason = $reason, s.created_at = $edge_created_at
            RETURN true AS ok
            """,
            collection_name=collection_name,
            newer_id=newer_event_id,
            older_id=older_event_id,
            reason=reason,
            edge_created_at=edge_created_at,
        ).single()
        return bool(rec and rec.get("ok"))

    def _apply_event_supersession(
        self,
        session: Any,
        *,
        collection_name: str,
        new_event_id: str,
        ev: dict[str, Any],
        snapshot_id: str,
        ingested_at: str,
    ) -> None:
        explicit: list[tuple[str, str]] = []
        sid = str(ev.get("supersedes_event_id") or "").strip()
        if sid:
            explicit.append((sid, "payload_supersedes_event_id"))
        for oid in ev.get("invalidates_event_ids") or []:
            if isinstance(oid, str) and oid.strip():
                explicit.append((oid.strip(), "payload_invalidates_event_ids"))
        seen: set[str] = set()
        for older_id, reason in explicit:
            if older_id == new_event_id or older_id in seen:
                continue
            seen.add(older_id)
            self._merge_event_supersedes(
                session,
                collection_name=collection_name,
                newer_event_id=new_event_id,
                older_event_id=older_id,
                reason=reason,
                edge_created_at=ingested_at,
            )

        if ev.get("disable_auto_supersedes"):
            return

        event_time = str(ev.get("event_time") or ingested_at)
        date_prefix = self._event_time_date_prefix(event_time)
        if not date_prefix:
            return
        canonical_event = str(ev.get("canonical_event") or "")
        canonical_subevent = str(ev.get("canonical_subevent") or "")
        normalized_subtype = str(ev.get("normalized_subtype") or "")
        row = session.run(
            """
            MATCH (old:Event {collection_name: $collection_name})
            WHERE old.source_snapshot_id <> $snapshot_id
              AND old.event_id <> $new_event_id
              AND old.canonical_event = $canonical_event
              AND old.canonical_subevent = $canonical_subevent
              AND old.normalized_subtype = $normalized_subtype
              AND substring(old.event_time, 0, 10) = $date_prefix
            RETURN old.event_id AS event_id
            ORDER BY old.created_at DESC
            LIMIT 1
            """,
            collection_name=collection_name,
            snapshot_id=snapshot_id,
            new_event_id=new_event_id,
            canonical_event=canonical_event,
            canonical_subevent=canonical_subevent,
            normalized_subtype=normalized_subtype,
            date_prefix=date_prefix,
        ).single()
        if not row or not row.get("event_id"):
            return
        older_id = str(row["event_id"])
        if older_id == new_event_id or older_id in seen:
            return
        self._merge_event_supersedes(
            session,
            collection_name=collection_name,
            newer_event_id=new_event_id,
            older_event_id=older_id,
            reason="auto_same_day_restatement",
            edge_created_at=ingested_at,
        )

    def _apply_event_causes(
        self,
        session: Any,
        *,
        collection_name: str,
        source_event_id: str,
        ev: dict[str, Any],
        ingested_at: str,
    ) -> None:
        """Persist (:Event)-[:CAUSES]->(:Event) per PRODUCT_ENHANCEMENT §8 (event-level causality)."""
        specs: list[tuple[str, float, str]] = []
        base_conf = float(ev.get("confidence", 0.6))
        base_conf = max(0.0, min(1.0, base_conf))
        desc = str(ev.get("description") or "").strip()[:2000]

        for entry in ev.get("causes") or []:
            if not isinstance(entry, dict):
                continue
            tid = str(entry.get("target_event_id") or "").strip()
            if not tid:
                continue
            p_raw = entry.get("probability")
            if isinstance(p_raw, (int, float)) and not isinstance(p_raw, bool):
                prob = max(0.0, min(1.0, float(p_raw)))
            else:
                prob = base_conf
            reason = str(entry.get("reason") or desc or "extraction_causes").strip()[:2000] or "extraction_causes"
            specs.append((tid, prob, reason))

        for tid in ev.get("causes_event_ids") or []:
            if isinstance(tid, str) and tid.strip():
                t = tid.strip()
                reason = desc or "causes_event_ids"
                specs.append((t, base_conf, reason[:2000]))

        seen: set[str] = set()
        for tgt_id, prob, reason in specs:
            if tgt_id == source_event_id or tgt_id in seen:
                continue
            seen.add(tgt_id)
            session.run(
                """
                MATCH (src:Event {event_id: $src, collection_name: $c})
                MATCH (tgt:Event {event_id: $tgt, collection_name: $c})
                WHERE src <> tgt
                MERGE (src)-[r:CAUSES]->(tgt)
                ON CREATE SET r.probability = $prob,
                              r.reason = $reason,
                              r.created_at = $ts
                """,
                src=source_event_id,
                tgt=tgt_id,
                c=collection_name,
                prob=prob,
                reason=reason,
                ts=ingested_at,
            ).consume()

    def _persist_triplet_facts(
        self,
        session: Any,
        *,
        collection_name: str,
        snapshot_id: str,
        ingested_at: str,
        ontology_id: str,
        triplets: Any,
    ) -> None:
        """Materialize extraction triplets as :TripletFact nodes linked from the snapshot (Cypher-queryable)."""
        if not isinstance(triplets, list):
            return
        for i, raw in enumerate(triplets):
            if not isinstance(raw, dict):
                continue
            subj = str(raw.get("subject") or raw.get("s") or "").strip()
            pred = str(raw.get("predicate") or raw.get("p") or "").strip().upper()
            obj = str(raw.get("object") or raw.get("o") or "").strip()
            if not subj or not pred or not obj:
                continue
            th = hashlib.sha256(f"{snapshot_id}:{i}:{subj}:{pred}:{obj}".encode("utf-8")).hexdigest()[:24]
            triplet_id = f"tr_{th}"
            session.run(
                """
                MATCH (snap:ChunkIngestSnapshot {snapshot_id: $sid, collection_name: $c})
                CREATE (tf:TripletFact {
                  triplet_id: $tid,
                  collection_name: $c,
                  source_snapshot_id: $sid,
                  ontology_id: $oid,
                  subject: $subj,
                  predicate: $pred,
                  object: $obj,
                  ingested_at: $ts
                })
                CREATE (snap)-[:ASSERTS_TRIPLET]->(tf)
                """,
                sid=snapshot_id,
                c=collection_name,
                tid=triplet_id,
                oid=ontology_id,
                subj=subj,
                pred=pred,
                obj=obj,
                ts=ingested_at,
            ).consume()

    def merge_event_supersession(
        self,
        *,
        collection_name: str,
        newer_event_id: str,
        older_event_id: str,
        reason: str | None,
    ) -> dict[str, Any] | None:
        collection_name = to_internal_collection_name(collection_name)
        edge_at = datetime.now(timezone.utc).isoformat()
        rsn = (reason or "").strip() or "manual_api"
        with self._driver.session(database=self._settings.database) as session:
            rec = session.run(
                """
                MATCH (new:Event {event_id: $newer_id, collection_name: $collection_name})
                MATCH (old:Event {event_id: $older_id, collection_name: $collection_name})
                MERGE (new)-[s:SUPERSEDES]->(old)
                ON CREATE SET s.reason = $reason, s.created_at = $edge_created_at
                RETURN new.event_id AS newer_event_id,
                       old.event_id AS older_event_id,
                       s.reason AS reason,
                       s.created_at AS created_at
                """,
                collection_name=collection_name,
                newer_id=newer_event_id,
                older_id=older_event_id,
                reason=rsn,
                edge_created_at=edge_at,
            ).single()
            if rec is None:
                return None
            return {
                "newer_event_id": rec.get("newer_event_id"),
                "older_event_id": rec.get("older_event_id"),
                "reason": rec.get("reason"),
                "created_at": rec.get("created_at"),
            }

    def event_supersession_detail(
        self,
        *,
        collection_name: str,
        event_id: str,
    ) -> dict[str, Any] | None:
        collection_name = to_internal_collection_name(collection_name)
        with self._driver.session(database=self._settings.database) as session:
            row = session.run(
                """
                MATCH (ev:Event {event_id: $event_id, collection_name: $collection_name})
                OPTIONAL MATCH (newer:Event {collection_name: $collection_name})-[:SUPERSEDES]->(ev)
                WITH ev, collect(DISTINCT newer.event_id) AS by_ids
                OPTIONAL MATCH (ev)-[:SUPERSEDES]->(older:Event {collection_name: $collection_name})
                RETURN ev,
                       [x IN by_ids WHERE x IS NOT NULL] AS superseded_by,
                       [x IN collect(DISTINCT older.event_id) WHERE x IS NOT NULL] AS supersedes
                """,
                collection_name=collection_name,
                event_id=event_id,
            ).single()
            if row is None or row.get("ev") is None:
                return None
            by_list = [x for x in (row.get("superseded_by") or []) if x]
            supersedes_list = [x for x in (row.get("supersedes") or []) if x]
            return {
                "event_id": event_id,
                "superseded_by_event_ids": by_list,
                "supersedes_event_ids": supersedes_list,
            }

    def ping(self) -> None:
        with self._driver.session(database=self._settings.database) as session:
            session.run("RETURN 1 AS ok").consume()

    @staticmethod
    def _snapshot_hit_from_props(props: dict[str, Any], similarity: float | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "snapshot_id": props.get("snapshot_id"),
            "chunk_id": props.get("chunk_id"),
            "doc_id": props.get("doc_id"),
            "bundle_id": props.get("bundle_id"),
            "canonical_event": props.get("canonical_event"),
            "canonical_subevent": props.get("canonical_subevent"),
            "ingested_at": props.get("ingested_at"),
            "publish_date": props.get("publish_date"),
            "decay_half_life_days": props.get("decay_half_life_days"),
            "extraction_text": props.get("extraction_text", "") or "",
        }
        if similarity is not None:
            row["similarity"] = round(float(similarity), 6)
        return row

    def search_snapshots(
        self,
        *,
        collection_name: str,
        query: str,
        limit: int = 10,
        canonical_event: str | None = None,
        query_embedding: list[float] | None = None,
        publish_date_min: str | None = None,
        publish_date_max: str | None = None,
        exclude_decay_suppressed: bool = True,
    ) -> list[dict[str, Any]]:
        collection_name = to_internal_collection_name(collection_name)
        if query_embedding is not None:
            return self._search_snapshots_vector(
                collection_name=collection_name,
                query_embedding=query_embedding,
                limit=limit,
                canonical_event=canonical_event,
                publish_date_min=publish_date_min,
                publish_date_max=publish_date_max,
                exclude_decay_suppressed=exclude_decay_suppressed,
            )

        q = (query or "").strip()
        if not q:
            return []

        cypher = """
        MATCH (snap:ChunkIngestSnapshot)
        WHERE snap.collection_name = $collection_name
          AND toLower(snap.extraction_text) CONTAINS toLower($q)
        """
        params: dict[str, Any] = {
            "collection_name": collection_name,
            "q": q,
            "limit": limit,
        }
        if canonical_event:
            cypher += " AND snap.canonical_event = $canonical_event\n"
            params["canonical_event"] = canonical_event
        if exclude_decay_suppressed:
            cypher += " AND snap.retrieval_decay_suppressed_at IS NULL\n"
        if publish_date_min:
            cypher += " AND snap.publish_date >= $publish_date_min\n"
            params["publish_date_min"] = publish_date_min
        if publish_date_max:
            cypher += " AND snap.publish_date <= $publish_date_max\n"
            params["publish_date_max"] = publish_date_max

        cypher += """
        RETURN snap
        ORDER BY snap.ingested_at DESC
        LIMIT $limit
        """

        rows: list[dict[str, Any]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, **params)
            for record in result:
                node = record["snap"]
                props = {k: node[k] for k in node.keys()}
                rows.append(self._snapshot_hit_from_props(props))
        return rows

    def _search_snapshots_vector(
        self,
        *,
        collection_name: str,
        query_embedding: list[float],
        limit: int,
        canonical_event: str | None,
        publish_date_min: str | None = None,
        publish_date_max: str | None = None,
        exclude_decay_suppressed: bool = True,
    ) -> list[dict[str, Any]]:
        if not query_embedding:
            return []
        index_name = self._settings.snapshot_vector_index_name
        if index_name:
            try:
                return self._search_snapshots_vector_index(
                    collection_name=collection_name,
                    query_embedding=query_embedding,
                    limit=limit,
                    canonical_event=canonical_event,
                    index_name=index_name,
                    publish_date_min=publish_date_min,
                    publish_date_max=publish_date_max,
                    exclude_decay_suppressed=exclude_decay_suppressed,
                )
            except Neo4jError:
                pass
        return self._search_snapshots_vector_scan(
            collection_name=collection_name,
            query_embedding=query_embedding,
            limit=limit,
            canonical_event=canonical_event,
            publish_date_min=publish_date_min,
            publish_date_max=publish_date_max,
            exclude_decay_suppressed=exclude_decay_suppressed,
        )

    def _search_snapshots_vector_index(
        self,
        *,
        collection_name: str,
        query_embedding: list[float],
        limit: int,
        canonical_event: str | None,
        index_name: str,
        publish_date_min: str | None = None,
        publish_date_max: str | None = None,
        exclude_decay_suppressed: bool = True,
    ) -> list[dict[str, Any]]:
        fetch_k = min(5000, max(limit * 25, limit, 25))
        cypher = """
        CALL db.index.vector.queryNodes($index_name, $fetch_k, $query_embedding)
        YIELD node AS snap, score
        WHERE snap.collection_name = $collection_name
        """
        params: dict[str, Any] = {
            "index_name": index_name,
            "fetch_k": fetch_k,
            "query_embedding": query_embedding,
            "collection_name": collection_name,
            "limit": limit,
        }
        if canonical_event:
            cypher += " AND snap.canonical_event = $canonical_event\n"
            params["canonical_event"] = canonical_event
        if exclude_decay_suppressed:
            cypher += " AND snap.retrieval_decay_suppressed_at IS NULL\n"
        if publish_date_min:
            cypher += " AND snap.publish_date >= $publish_date_min\n"
            params["publish_date_min"] = publish_date_min
        if publish_date_max:
            cypher += " AND snap.publish_date <= $publish_date_max\n"
            params["publish_date_max"] = publish_date_max
        cypher += """
        RETURN snap, score
        ORDER BY score DESC
        LIMIT $limit
        """
        rows: list[dict[str, Any]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, **params)
            for record in result:
                node = record["snap"]
                props = {k: node[k] for k in node.keys()}
                score = record.get("score")
                sim = float(score) if score is not None else None
                rows.append(self._snapshot_hit_from_props(props, similarity=sim))
        return rows

    def _search_snapshots_vector_scan(
        self,
        *,
        collection_name: str,
        query_embedding: list[float],
        limit: int,
        canonical_event: str | None,
        publish_date_min: str | None = None,
        publish_date_max: str | None = None,
        exclude_decay_suppressed: bool = True,
    ) -> list[dict[str, Any]]:
        scan_cap = max(1, self._settings.snapshot_vector_scan_limit)
        cypher = """
        MATCH (snap:ChunkIngestSnapshot {collection_name: $collection_name})
        WHERE snap.embedding IS NOT NULL
        """
        params: dict[str, Any] = {
            "collection_name": collection_name,
            "scan_cap": scan_cap,
        }
        if canonical_event:
            cypher += " AND snap.canonical_event = $canonical_event\n"
            params["canonical_event"] = canonical_event
        if exclude_decay_suppressed:
            cypher += " AND snap.retrieval_decay_suppressed_at IS NULL\n"
        if publish_date_min:
            cypher += " AND snap.publish_date >= $publish_date_min\n"
            params["publish_date_min"] = publish_date_min
        if publish_date_max:
            cypher += " AND snap.publish_date <= $publish_date_max\n"
            params["publish_date_max"] = publish_date_max
        cypher += """
        RETURN snap
        LIMIT $scan_cap
        """
        scored: list[tuple[float, dict[str, Any]]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, **params)
            for record in result:
                node = record["snap"]
                props = {k: node[k] for k in node.keys()}
                emb = to_float_list(props.get("embedding"))
                if emb is None:
                    continue
                sim = cosine_similarity(query_embedding, emb)
                if sim is None:
                    continue
                scored.append((sim, props))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            self._snapshot_hit_from_props(props, similarity=sim)
            for sim, props in scored[: max(1, limit)]
        ]

    def search_events(
        self,
        *,
        collection_name: str,
        limit: int = 20,
        canonical_event: str | None = None,
        canonical_subevent: str | None = None,
        query: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        include_superseded: bool = False,
        exclude_decay_suppressed_snapshots: bool = True,
    ) -> list[dict[str, Any]]:
        collection_name = to_internal_collection_name(collection_name)
        cypher = """
        MATCH (ev:Event {collection_name: $collection_name})-[:DERIVED_FROM]->(snap:ChunkIngestSnapshot {collection_name: $collection_name})
        WHERE 1=1
        """
        params: dict[str, Any] = {
            "collection_name": collection_name,
            "limit": limit,
            "include_superseded": include_superseded,
        }
        if canonical_event:
            cypher += " AND ev.canonical_event = $canonical_event\n"
            params["canonical_event"] = canonical_event
        if canonical_subevent:
            cypher += " AND ev.canonical_subevent = $canonical_subevent\n"
            params["canonical_subevent"] = canonical_subevent
        if query and query.strip():
            cypher += " AND toLower(ev.description) CONTAINS toLower($query)\n"
            params["query"] = query.strip()
        if start_time:
            cypher += " AND ev.event_time >= $start_time\n"
            params["start_time"] = start_time
        if end_time:
            cypher += " AND ev.event_time <= $end_time\n"
            params["end_time"] = end_time
        if not include_superseded:
            cypher += (
                " AND NOT (ev)<-[:SUPERSEDES]-(:Event {collection_name: $collection_name})\n"
            )
        if exclude_decay_suppressed_snapshots:
            cypher += " AND snap.retrieval_decay_suppressed_at IS NULL\n"
        cypher += """
        OPTIONAL MATCH (sup_by:Event {collection_name: $collection_name})-[sr:SUPERSEDES]->(ev)
        WITH ev, sup_by, sr
        ORDER BY sr.created_at DESC NULLS LAST
        WITH ev, collect(sup_by)[0] AS sup_by0, collect(sr)[0] AS sr0
        RETURN ev,
               CASE WHEN sup_by0 IS NULL THEN null ELSE sup_by0.event_id END AS superseded_by_event_id,
               CASE WHEN sr0 IS NULL THEN null ELSE sr0.reason END AS supersession_reason
        ORDER BY ev.event_time DESC, ev.created_at DESC
        LIMIT $limit
        """
        rows: list[dict[str, Any]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, **params)
            for record in result:
                node = record["ev"]
                props = {k: node[k] for k in node.keys()}
                rows.append(
                    {
                        "event_id": props.get("event_id"),
                        "collection_name": props.get("collection_name"),
                        "canonical_event": props.get("canonical_event"),
                        "canonical_subevent": props.get("canonical_subevent"),
                        "normalized_subtype": props.get("normalized_subtype"),
                        "event_time": props.get("event_time"),
                        "confidence": props.get("confidence"),
                        "direction": props.get("direction"),
                        "magnitude": props.get("magnitude"),
                        "probability": props.get("probability"),
                        "description": props.get("description"),
                        "source_snapshot_id": props.get("source_snapshot_id"),
                        "superseded_by_event_id": record.get("superseded_by_event_id"),
                        "supersession_reason": record.get("supersession_reason"),
                    }
                )
        return rows

    def list_rag_collections(self) -> list[dict[str, Any]]:
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(
                """
                MATCH (c:RagCollection)
                RETURN c.name AS collection_name, c.ontology_id AS ontology_id
                ORDER BY c.name
                """
            )
            return [dict(r) for r in result]

    def upsert_rag_collection(self, *, collection_name: str, ontology_id: str) -> dict[str, Any]:
        collection_name = to_internal_collection_name(collection_name)
        with self._driver.session(database=self._settings.database) as session:
            row = session.run(
                """
                MERGE (c:RagCollection {name: $name})
                SET c.ontology_id = $ontology_id
                RETURN c.name AS collection_name, c.ontology_id AS ontology_id
                """,
                name=collection_name,
                ontology_id=ontology_id,
            ).single()
            if row is None:
                raise RuntimeError("Failed to upsert RagCollection")
            return dict(row)

    def get_rag_collection(self, *, collection_name: str) -> dict[str, Any] | None:
        collection_name = to_internal_collection_name(collection_name)
        with self._driver.session(database=self._settings.database) as session:
            row = session.run(
                """
                MATCH (c:RagCollection {name: $name})
                RETURN c.name AS collection_name, c.ontology_id AS ontology_id
                LIMIT 1
                """,
                name=collection_name,
            ).single()
            return dict(row) if row is not None else None

    def clear_rag_collections(self) -> None:
        with self._driver.session(database=self._settings.database) as session:
            session.run("MATCH (c:RagCollection) DETACH DELETE c").consume()

    def fetch_snapshots_for_decay_evaluation(
        self,
        *,
        collection_name: str,
        skip: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        collection_name = to_internal_collection_name(collection_name)
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(
                """
                MATCH (s:ChunkIngestSnapshot {collection_name: $c})
                WHERE s.retrieval_decay_suppressed_at IS NULL
                RETURN s.snapshot_id AS snapshot_id,
                       s.canonical_subevent AS canonical_subevent,
                       s.publish_date AS publish_date,
                       s.ingested_at AS ingested_at,
                       s.decay_half_life_days AS decay_half_life_days
                ORDER BY s.ingested_at ASC
                SKIP $skip
                LIMIT $limit
                """,
                c=collection_name,
                skip=skip,
                limit=limit,
            )
            return [dict(r) for r in result]

    def mark_snapshot_decay_suppressed(
        self,
        *,
        collection_name: str,
        snapshot_id: str,
        suppressed_at_iso: str,
    ) -> None:
        collection_name = to_internal_collection_name(collection_name)
        with self._driver.session(database=self._settings.database) as session:
            session.run(
                """
                MATCH (s:ChunkIngestSnapshot {snapshot_id: $sid, collection_name: $c})
                SET s.retrieval_decay_suppressed_at = $ts
                """,
                sid=snapshot_id,
                c=collection_name,
                ts=suppressed_at_iso,
            ).consume()

    def entity_collection_connections(
        self,
        *,
        entity_name: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        normalized = self._norm(entity_name)
        cypher = """
        MATCH (ge:GlobalEntity {normalized_name: $normalized})
        MATCH (ce:CollectionEntity)-[:REFERS_TO]->(ge)
        OPTIONAL MATCH (snap:ChunkIngestSnapshot)-[r:INVOLVES]->(ce)
        RETURN ce.collection_name AS collection_name,
               ge.display_name AS entity_name,
               ge.entity_type AS entity_type,
               collect(DISTINCT r.role)[0..5] AS observed_roles,
               count(snap) AS mention_count
        ORDER BY mention_count DESC
        LIMIT $limit
        """
        rows: list[dict[str, Any]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, normalized=normalized, limit=limit)
            for record in result:
                rows.append(
                    {
                        "collection_name": record.get("collection_name"),
                        "entity_name": record.get("entity_name"),
                        "entity_type": record.get("entity_type"),
                        "observed_roles": record.get("observed_roles") or [],
                        "mention_count": int(record.get("mention_count") or 0),
                    }
                )
        return rows

    def chunk_timeline(
        self,
        *,
        collection_name: str,
        chunk_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        collection_name = to_internal_collection_name(collection_name)
        cypher = """
        MATCH (ref:ChunkRef {chunk_id: $chunk_id, collection_name: $collection_name})
        MATCH (snap:ChunkIngestSnapshot)-[:OF_CHUNK]->(ref)
        OPTIONAL MATCH (snap)-[:SUPERSEDES]->(older:ChunkIngestSnapshot)
        RETURN snap, older.snapshot_id AS supersedes_snapshot_id
        ORDER BY snap.ingested_at DESC
        LIMIT $limit
        """
        params = {
            "collection_name": collection_name,
            "chunk_id": chunk_id,
            "limit": limit,
        }
        rows: list[dict[str, Any]] = []
        with self._driver.session(database=self._settings.database) as session:
            result = session.run(cypher, **params)
            for record in result:
                node = record["snap"]
                props = {k: node[k] for k in node.keys()}
                rows.append(
                    {
                        "snapshot_id": props.get("snapshot_id"),
                        "chunk_id": props.get("chunk_id"),
                        "canonical_event": props.get("canonical_event"),
                        "canonical_subevent": props.get("canonical_subevent"),
                        "ingested_at": props.get("ingested_at"),
                        "supersedes_snapshot_id": record.get("supersedes_snapshot_id"),
                    }
                )
        return rows
