---
name: temporial-graph-rag
description: Builds and maintains a financial temporal-graph RAG system with uv, FastAPI, and HTTP chunk ingestion for stock-market temporal events. Use when implementing APIs, ingestion, graph/RAG, or any feature in this repository; when the user mentions chunks, events, impacts, causality, or GraphRAG for this project.
---

# Temporial Graph RAG (Financial)

## Context

Event-centric temporal graph for market data: events, entities, impacts, causality, append-only history. Full architecture and phases live in [README.md](../../README.md) at repo root.

## Stack (non-negotiable)

- **Package/runtime**: `uv` for dependencies, virtual env, and runnable commands (`uv run`, `uv sync`, `uv add`).
- **API**: FastAPI for the HTTP surface; async-friendly patterns where I/O-bound.

## Ingestion model

- **Primary input**: **Chunks** submitted to the system (e.g. POST endpoints), not only raw files on disk unless explicitly added later.
- Preserve provenance (source id, timestamps) on ingested chunks for temporal RAG and audit.
- Align with README: event-first modeling, temporal edges, append-only updates where applicable.

## Implementation workflow

1. **Read** relevant README sections (data model, ingestion, query layer) before large design changes.
2. **uv**: add deps with `uv add`; run app/tests with `uv run`.
3. **API**: version routes if public; validate payloads with Pydantic models; return clear error shapes.
4. **RAG/graph**: separate retrieval, graph operations, and generation; keep embedding/index configuration in one place.
5. **Tests**: add tests alongside new endpoints and ingestion paths.

## Naming

- Repository/path uses **temporial**; use **temporal** for correct technical terms (temporal graph, temporal edges) in docs and code comments when explaining behavior.
