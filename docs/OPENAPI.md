# HTTP API — OpenAPI guide

This document **narrates** the REST API. The **machine-readable OpenAPI 3.1** specification is **[openapi.json](./openapi.json)** (generated from the FastAPI application). Import that file into **Swagger UI**, **Postman**, **Insomnia**, or codegen tools.

---

## 1. Specification file

| File | Format | Source of truth |
| ---- | ------ | ---------------- |
| [`docs/openapi.json`](./openapi.json) | OpenAPI 3.1 JSON | Regenerated from `temporial_graph_rag.api.main:app` |

**Regenerate** after changing routes, parameters, or Pydantic models:

```bash
cd /path/to/temporial_graph
uv run python <<'PY'
import json
from pathlib import Path
from temporial_graph_rag.api.main import app
spec = app.openapi()
spec.setdefault("servers", [{"url": "http://127.0.0.1:8000"}])
Path("docs").mkdir(exist_ok=True)
Path("docs/openapi.json").write_text(json.dumps(spec, indent=2))
PY
```

Interactive docs (when server is running):

- Swagger UI: `http://127.0.0.1:8000/docs` (FastAPI default)
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## 2. Base URL and versioning

- **Version prefix:** `/v1` for all collection-scoped and ingest routes.
- **Servers** (embedded in `openapi.json`): local `http://127.0.0.1:8000` plus a relative `/` entry.

There is **no API key or bearer auth** in the current application; deploy behind a gateway if needed.

---

## 3. Content type and errors

- Requests and responses use **`application/json`** unless noted otherwise.
- **422 Unprocessable Entity** — Pydantic validation (`HTTPValidationError` in spec) for malformed bodies or invalid types.
- **400 Bad Request** — Business validation (e.g. invalid ontology pair, empty query).
- **404 Not Found** — Unknown collection or missing graph row where applicable.
- **409 Conflict** — Duplicate collection name on create.
- **502 Bad Gateway** — Neo4j driver errors, LLM failures, or embedding failures surfaced as upstream errors.
- **503 Service Unavailable** — Neo4j disabled when a route **requires** the graph store, or LLM health probe failure on `/v1/health/llm`.

Error bodies are typically FastAPI’s `{"detail": "..."}` or validation detail arrays.

---

## 4. Endpoint catalog

Below, **Neo4j required** means `NEO4J_ENABLED=true` and a reachable database; otherwise the handler returns **503** for graph-backed operations.

### 4.1 Health

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| GET | `/health` | No | Liveness: `{"status":"ok"}`. |
| GET | `/v1/health/llm` | No | Probes **llm-service** via `GET /llm/models` through `LLMClient`. **503** if unreachable. |
| GET | `/v1/health/neo4j` | Optional | Returns `{"neo4j":"disabled"}` when off; when enabled, **ping** and return `{"neo4j":"ok"}` or **503**. |

### 4.2 Collections (registry)

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/v1/collections` | List bindings: `collection_name`, `ontology_id`. |
| GET | `/v1/collections/{collection_name}` | Get one collection detail: `collection_name`, `ontology_id`, `ontology_version` (if ontology file exists), and `registry_backend` (`memory` or `neo4j`). **404** if missing. |
| POST | `/v1/collections` | Body: `CreateCollectionRequest` — `collection_name`, `ontology_id`. Validates ontology file exists. **409** if name exists. |
| POST | `/v1/collections/get-or-create` | Body: `CreateCollectionRequest`. Returns same detail fields + `created` boolean. `created=true` only on first create; `false` if already present with same ontology. **409** if collection exists with different ontology. |

Registry backend behavior:

- **`NEO4J_ENABLED=false`** → in-memory registry backend (`registry_backend = "memory"`).
- **`NEO4J_ENABLED=true`** → persistent Neo4j-backed registry via `RagCollection` nodes (`registry_backend = "neo4j"`).

### 4.2.1 `get-or-create` semantics (human + agent reference)

Input: `{"collection_name": "<name>", "ontology_id": "<id>"}`.

Deterministic outcomes:

1. **Collection absent + ontology exists** → creates collection, returns `200` with `created: true`.
2. **Collection present + same ontology** → returns existing row, `200` with `created: false`.
3. **Collection present + different ontology** → returns `409`.
4. **Collection absent + ontology file missing** → returns `400`.

This endpoint is safe for idempotent orchestration loops in agents and pipelines.

### 4.3 Ontology preview

| Method | Path | Query params | Description |
| ------ | ---- | ------------ | ----------- |
| GET | `/v1/collections/{collection_name}/impact-prior` | `canonical_event`, `canonical_subevent` (required) | Returns merged impact prior dict for that pair. **400** if pair invalid for ontology. |

### 4.4 Snapshot search (chunk ingest snapshots)

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| GET | `/v1/collections/{collection_name}/snapshots/search` | **Yes** | Params: `q` (required), `limit` (1–50), `canonical_event` optional, `mode` = `lexical` \| `vector`. Vector mode calls embeddings service for `q`. **400** if `q` empty. |

Response: `SnapshotSearchResponse` with `hits[]` (`SnapshotSearchHit`: ids, labels, `extraction_text`, optional `similarity`, etc.).

### 4.5 Chunk timeline (supersession chain)

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| GET | `/v1/collections/{collection_name}/chunks/{chunk_id}/timeline` | **Yes** | Param: `limit` (1–200). Ordered snapshot lineage for supersession debugging. |

### 4.6 Cross-collection entity network

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| GET | `/v1/network/entities/{entity_name}/collections` | **Yes** | Param: `limit` (1–100). Entity → collections / roles / mention counts. |

### 4.7 Event search

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| GET | `/v1/collections/{collection_name}/events/search` | **Yes** | Params: `limit` (1–100), `canonical_event`, `canonical_subevent`, `q`, `start_time`, `end_time`, `include_superseded` (bool), **`exclude_decay_suppressed_snapshots`** (bool, default **true**). |

### 4.8 Event supersession (explicit)

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| POST | `/v1/collections/{collection_name}/events/supersession` | **Yes** | Body: `CreateEventSupersessionRequest` — `newer_event_id`, `older_event_id`, optional `reason`. **400** if ids equal. **404** if events missing. |
| GET | `/v1/collections/{collection_name}/events/{event_id}/supersession` | **Yes** | Detail: superseded-by and supersedes id lists. **404** if event not found. |

### 4.9 RAG

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| POST | `/v1/collections/{collection_name}/rag/answer` | **Yes** | Body: `RagAnswerRequest` — `question`, `top_k` (1–30), `retrieval_mode` `lexical` \| `vector`. Retrieves snapshots, applies **decay** filter and ranking, synthesizes answer. Empty-context message if nothing passes decay threshold. |
| POST | `/v1/collections/{collection_name}/rag/multi_step` | **Yes** | Body: `MultiStepRagRequest` — `question`, `max_steps` (1–25). Planner + tool loop (`search_documents`, `search_events`, `trend_analysis`). Response: `initial_plan`, `answer`, `steps` (tool traces / parse errors). **502** on retriever failure. |

### 4.10 Ingest

| Method | Path | Neo4j | Description |
| ------ | ---- | ----- | ----------- |
| POST | `/v1/ingest/chunks` | No | Body: `IngestBatchRequest` — `collection_name`, `ontology_id`, `chunks[]`. Validates ontology and each chunk’s event pair; returns accepted count. Ensures collection binding. |
| POST | `/v1/ingest/chunks/process` | Optional | Same body; runs **ChunkProcessor** (LLM + scoring). If Neo4j enabled, persists each chunk and increments `persisted_snapshots`. Returns `processed[]` summaries and `persisted_snapshots`. |

---

## 5. Shared schemas (summary)

Full field lists and nested types are in **`components.schemas`** inside [openapi.json](./openapi.json). Highlights:

- **`IngestChunk`** — `chunk_id`, `content`, `type`, `doc_id`, `bundle_id`, `canonical_event`, `canonical_subevent`, `publish_date`, optional navigation/metadata; `title_summary` required for `image` type.
- **`IngestBatchRequest` / `IngestBatchResponse` / `IngestProcessResponse`** — Batch wrapper and `ProcessedChunkSummary` (impact, entities, extracted events, embedding metadata).
- **`RagAnswerRequest` / `RagAnswerResponse`** — Question, sources list.
- **`MultiStepRagRequest` / `MultiStepRagResponse`** — Plan + steps array (loosely typed `dict` for flexibility).
- **`CollectionDetailResponse` / `CollectionGetOrCreateResponse`** — Collection admin payloads including `registry_backend` and idempotent `created` signal.
- **Event / supersession / search hits** — As modeled in `models/query.py`.

---

## 6. Relationship to notebook and product docs

- **Multi-step RAG** implements the same *interaction pattern* as [`temporal_agents.ipynb`](../temporal_agents.ipynb)’s `MultiStepRetriever` (plan → tool JSON loop → final answer), but exposes it as **one HTTP POST** returning structured `steps`.
- **Financial decay and event-first modeling** follow [`PRODUCT_ENHANCEMENT.md`](../PRODUCT_ENHANCEMENT.md); HTTP clients consume **collections** and **ontology-driven** behavior without sending priors on every request (except via ontology files on the server).

For deeper behavior (decay formula, tool internals, jobs), see [DEVELOPER_ENHANCEMENTS.md](./DEVELOPER_ENHANCEMENTS.md).
