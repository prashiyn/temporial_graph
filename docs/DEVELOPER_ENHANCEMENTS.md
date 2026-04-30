# Developer guide — enhancements, retrieval, decay, ingestion

This guide is for engineers extending **multi-agent retrieval**, **decay**, **ingestion**, and **graph-backed search**. It complements [DESIGN.md](./DESIGN.md) (architecture narrative) and [OPENAPI.md](./OPENAPI.md) / [openapi.json](./openapi.json) (HTTP layer).

**References:**

- [`temporal_agents.ipynb`](../temporal_agents.ipynb) — original multi-step planner/executor and tool patterns (§4.1-style cells: `initial_planner`, `factual_qa`, `trend_analysis`, `MultiStepRetriever`).
- [`PRODUCT_ENHANCEMENT.md`](../PRODUCT_ENHANCEMENT.md) — financial extensions (events, impact, decay, append-only behavior).

---

## 1. Repository layout (relevant packages)

| Path | Role |
| ---- | ---- |
| `src/temporial_graph_rag/api/main.py` | FastAPI routes, wiring to store, LLM, retrieval |
| `src/temporial_graph_rag/models/chunk.py` | `IngestChunk`, `ChunkType`, `extraction_text` |
| `src/temporial_graph_rag/models/ingest.py` | Batch ingest request/response, `ProcessedChunkSummary` |
| `src/temporial_graph_rag/models/query.py` | Search/RAG DTOs |
| `src/temporial_graph_rag/pipeline/processor.py` | `ChunkProcessor`, entity resolution assist |
| `src/temporial_graph_rag/pipeline/scoring.py` | Impact scoring vs ontology |
| `src/temporial_graph_rag/ontology/loader.py` | `Ontology`, `load_ontology`, `get_decay_weight_threshold`, publish windows |
| `src/temporial_graph_rag/graph/store.py` | Neo4j persistence and search |
| `src/temporial_graph_rag/retrieval/` | Decay, prompts, tools, multi-step loop, optional Redis session store |
| `src/temporial_graph_rag/llm/` | `LLMClient`, `LLMServiceConfig`, per-task env overrides |
| `src/temporial_graph_rag/jobs/decay_suppress_weekly.py` | Weekly decay suppression batch |
| `ontologies/*.json` | Event taxonomy, priors, supersession, decay thresholds |

---

## 2. Multi-step retrieval (“multi-agent” pattern)

### 2.1 Conceptual model

We implement a **two-role** pattern aligned with [`temporal_agents.ipynb`](../temporal_agents.ipynb):

1. **Planner** — One shot: given the user question, produce a structured natural-language **research plan** (the notebook’s “initial planner” spirit).
2. **Executor** — Repeated turns: the model must output **strict JSON** describing either:
   - `{"action":"tool","tool_name":...,"arguments":{...}}`, or
   - `{"action":"final","answer":...}`.

The server runs tools **synchronously**, appends JSON results to an internal **transcript**, and sends the transcript back to the model on the next turn. This is the same **ReAct-style** constraint as the notebook’s `MultiStepRetriever`, adapted to **Neo4j** and **financial collections**.

### 2.2 Code entry points

- **`MultiStepRetriever`** — `src/temporial_graph_rag/retrieval/multi_step.py`
  - Constructor builds `RetrievalTools` with `RetrievalToolContext` (`store`, `llm`, `collection_name`, `ontology`).
  - `run(question)` → `MultiStepRetrievalResult(answer, initial_plan, steps)`.

- **Prompts** — `src/temporial_graph_rag/retrieval/prompts.py`
  - `PLANNER_SYSTEM`, `planner_user_message` — ABC/research framing from the notebook, tools renamed to `search_documents`, `search_events`, `trend_analysis`.
  - `executor_system_message`, `executor_user_turn`, `TOOL_CATALOG_TEXT` — JSON-only protocol.
  - `TREND_SYNTHESIS_SYSTEM` — used after grid search in `trend_analysis`.

- **JSON extraction** — `src/temporial_graph_rag/retrieval/json_extract.py`
  - Tolerates fenced ```json blocks; raises `ValueError` if no object found (executor records parse errors in `steps`).

### 2.3 Tools (executor surface)

Implemented in `src/temporial_graph_rag/retrieval/tools.py`:

| Tool | Notebook analogue | Behavior |
| ---- | ----------------- | -------- |
| `search_documents` | `factual_qa` | `Neo4jGraphStore.search_snapshots` with optional vector embeddings via `LLMClient.embeddings`; `publish_date_start` / `publish_date_end`; `exclude_decay_suppressed=True`; then `enrich_snapshot_hits_with_decay` + `sort_snapshot_hits_by_decay_and_similarity`. Returns JSON string of hits. |
| `search_events` | Graph event query | `search_events` on store with superseded excluded and decay-suppressed snapshots excluded. |
| `trend_analysis` | `trend_analysis` | Nested loops over `companies` × `topic_filter` calling `search_documents` (lexical) with date window; concatenates sections; calls **`retrieval_trend_synthesis`** LLM task; returns summary + metadata. |

Unknown tool names return JSON `{"error":"unknown_tool: ..."}`.

### 2.4 LLM tasks (env-configurable)

Configured in `src/temporial_graph_rag/llm/config.py` (`LLMServiceConfig.default_tasks()`):

| Task key | Used by |
| -------- | ------- |
| `retrieval_planner` | Multi-step plan |
| `retrieval_step` | Executor loop |
| `retrieval_trend_synthesis` | Trend tool |
| `entity_resolution_assist` | Ingest pipeline (optional) |
| `answer_synthesis` | Single-shot RAG |
| `statement_extraction`, `temporal_range_extraction`, `event_or_triplet_extraction`, `embeddings` | `ChunkProcessor` |

Override per task with env vars `LLM_TASK_<NAME>_PROVIDER`, `LLM_TASK_<NAME>_MODEL`, etc.

### 2.5 Session store (optional Redis)

`src/temporial_graph_rag/retrieval/session_store.py`:

- `MemoryRetrievalSessionStore` — in-process.
- `RedisRetrievalSessionStore` — requires optional dependency: `uv sync --extra redis`.
- `session_store_from_env()` — returns Redis store when `REDIS_URL` is set and connection succeeds.

**Extension idea:** Thread a `session_id` from the API into the retriever to persist transcripts across HTTP requests (not required for current single-request `max_steps` loop).

---

## 3. Decay logic

### 3.1 Purpose

Per [`PRODUCT_ENHANCEMENT.md`](../PRODUCT_ENHANCEMENT.md) §5–§6 and §9, older information should **lose prominence**. We implement:

1. **Continuous decay weight** at retrieval time (and for the weekly job’s comparison).
2. **Per–canonical-subevent floor** (`decay_weight_threshold`) so stale content can be **filtered** or **marked** for suppression.

### 3.2 Formula

`src/temporial_graph_rag/retrieval/decay.py`:

- **Reference time** — Prefer parsed **publish** instant; fall back to **ingested** time (`reference_instant_for_decay` / `parse_publish_instant`).
- **Half-life** — From snapshot row field `decay_half_life_days` (sourced from ontology impact priors at ingest); default 14 if missing/invalid.
- **Weight** — `0.5 ** (age_days / half_life_days)` clamped to age ≥ 0; stays in (0, 1]. At reference time, weight = 1.

### 3.3 Ontology configuration

`ontologies/*.json` → `decay_retrieval`:

```json
"decay_retrieval": {
  "default": { "decay_weight_threshold": 0.1 },
  "subevent_overrides": { "RESULTS": { "decay_weight_threshold": 0.15 } }
}
```

`Ontology.get_decay_weight_threshold(canonical_subevent)` merges default and overrides; invalid values fall back to **0.1**.

### 3.4 Retrieval usage

- **`enrich_snapshot_hits_with_decay(hits, ontology)`** — Adds `decay_weight`, `decay_weight_threshold`; **drops** hits with `decay_weight < threshold`.
- **`sort_snapshot_hits_by_decay_and_similarity(hits)`** — Sort key prefers `decay_weight * similarity` when `similarity` is present; else decay-only.

Single-shot RAG (`rag/answer`) uses both after `search_snapshots`.

Multi-step **`search_documents`** tool applies the same enrichment and sort before returning JSON to the model.

### 3.5 Graph property: decay suppression (weekly job)

`src/temporial_graph_rag/jobs/decay_suppress_weekly.py`:

- Iterates registered collections, loads each ontology, pages snapshots via `fetch_snapshots_for_decay_evaluation`.
- Computes `decay_weight` at job **now**; if `weight < threshold`, sets **`retrieval_decay_suppressed_at`** on the snapshot (append-friendly; does not delete nodes).
- Configure page size: `DECAY_JOB_PAGE_SIZE` (see `.env.sample`).

Store search paths accept **`exclude_decay_suppressed`** so suppressed snapshots are omitted from retrieval unless explicitly included.

**Operational note:** Schedule weekly (cron/Kubernetes CronJob) with Neo4j enabled and `.env` loaded:

`uv run python -m temporial_graph_rag.jobs.decay_suppress_weekly`

---

## 4. Content ingestion

### 4.1 Validate-only path

`POST /v1/ingest/chunks` — Ensures collection binding exists (or creates via `ensure_binding`), loads ontology, validates each chunk’s event pair and basic rules. **Does not** call LLM or Neo4j.

### 4.2 Full process path

`POST /v1/ingest/chunks/process`:

1. **`ChunkProcessor.process_chunk(chunk, ontology=...)`**
   - Builds `extraction_text` from content + summary (images use summary only).
   - Sequential LLM calls (statement → temporal → event/triplet → embeddings).
   - Predicate normalization against ontology.
   - **`score_impact`**.
   - **`_extract_entities`** then optional **`_entity_resolution_assist`** if `ENTITY_RESOLUTION_ASSIST_ENABLED` is truthy.
   - Returns **`ProcessedChunk`** (includes `entities`, `extracted_events`, embedding vector, impact fields).

2. **Persistence** — If `NEO4J_ENABLED` and store is non-null, `persist_chunk_snapshot(...)` writes snapshot + events + edges (implementation in `graph/store.py`). If Neo4j is disabled, `persisted_snapshots` stays 0 but **processed** summaries are still returned (useful for dry runs).

### 4.3 Neo4j: stable event ids, event→event causality, triplets

`Neo4jGraphStore.persist_chunk_snapshot` (`graph/store.py`):

- **`Neo4jGraphStore.graph_event_id(...)`** — If an extracted event includes **`stable_event_id`**, that string becomes the Neo4j **`Event.event_id`** (trimmed, max 256 chars). Otherwise the id is the previous deterministic `evt_{hash}` from snapshot index + canonical labels + `event_time`. Use **`stable_event_id`** when another ingest (or the same batch ordering) must reference the event in **`causes_event_ids`** or **`causes`**.
- **Event→event `CAUSES`** — After each snapshot’s events are created, the store merges **`(:Event)-[:CAUSES]->(:Event)`** for:
  - **`causes`:** `[{ "target_event_id", "probability"?, "reason"? }, ...]` (also accepts legacy key `"event_id"` for the target).
  - **`causes_event_ids`:** list of target `event_id` strings; edge **`probability`** defaults to the source event’s **`confidence`**; **`reason`** defaults to description or `"causes_event_ids"`.
  - Edges are only created when **both** events exist in the **same** `collection_name`. **Order ingests** so targets exist before sources (or run a second ingest pass for causal links).
- **`TripletFact`** — For each item in **`event_or_triplet_extraction.triplets`** with **`subject`**, **`predicate`**, **`object`** (aliases `s` / `p` / `o`), creates **`(:TripletFact)`** and **`(:ChunkIngestSnapshot)-[:ASSERTS_TRIPLET]->(:TripletFact)`**. Predicate is uppercased to match ontology normalization.

**Coexistence:** **`(:ChunkIngestSnapshot)-[:CAUSES]->(:MarketTarget)`** remains the coarse “snapshot → price proxy” link from impact scoring; **Event→Event `CAUSES`** is the PRODUCT_ENHANCEMENT-style causal link between structured events.

### 4.4 Data quality: entity resolution assist

Mirrors the **EntityResolution** idea from [`temporal_agents.ipynb`](../temporal_agents.ipynb) in a **minimal** way: one LLM JSON-shaping pass over extracted entities with excerpt context. It does **not** maintain a deduplicated entity table yet; graph upsert policy lives in the store layer.

### 4.5 Neo4j integration tests (collection isolation)

`tests/test_neo4j_isolation_integration.py` exercises **live Neo4j** when enabled:

- Set **`NEO4J_INTEGRATION_TEST=1`**, **`NEO4J_PASSWORD`**, and a reachable **`NEO4J_URI`** (and usual **`NEO4J_USER`** / **`NEO4J_DATABASE`**). The fixture temporarily sets **`NEO4J_ENABLED=true`** for settings resolution.
- Covers: **no cross-collection snapshot leakage**, **Event `CAUSES` Event** (string list + rich `causes` list), **`ASSERTS_TRIPLET` → `TripletFact`**.
- Without the env flag, tests **skip** so default CI stays offline.

---

## 5. Retrieval without multi-step

### 5.1 Snapshot search API

`GET /v1/collections/{collection_name}/snapshots/search`

- Query param `q` (required), `mode=lexical|vector`, `limit`, optional `canonical_event`.
- Vector mode embeds `q` via LLM service.
- Decay filtering may differ from RAG path depending on store method; consult `Neo4jGraphStore.search_snapshots` for `exclude_decay_suppressed` and publish range filters.

### 5.2 Event search API

`GET /v1/collections/{collection_name}/events/search`

- Filters: time range, canonical event/subevent, text `q`, `include_superseded`, **`exclude_decay_suppressed_snapshots`** (default true).

### 5.3 Single-shot RAG

`POST /v1/collections/{collection_name}/rag/answer`

- Fetches expanded candidate list, applies decay enrich + sort, truncates to `top_k`, builds context snippets, calls `answer_synthesis`.

---

## 6. Extension checklist

When adding a new **retrieval tool**:

1. Implement method on `RetrievalTools` and branch in `dispatch`.
2. Document fields in `prompts.TOOL_CATALOG_TEXT` and `PLANNER_SYSTEM` bullet list.
3. Add tests (mock store/LLM) if logic is non-trivial.
4. Regenerate **`docs/openapi.json`** only if HTTP API changes (OpenAPI doc is for REST; tools are internal to multi-step).

When adding **ontology knobs**:

1. Extend [`schemas/ontology.schema.json`](../schemas/ontology.schema.json), update `load_ontology` / `Ontology` if new top-level sections are required, and document in [ONTOLOGY.md](./ONTOLOGY.md).
2. Document defaults in [DESIGN.md](./DESIGN.md) and unit-test loader edge cases.

When changing **decay semantics**:

1. Update `decay.py`, weekly job, and any store Cypher filters together.
2. Keep append-only discipline: prefer new properties or relationships over destructive deletes.

---

## 7. Local development and tests

### 7.1 Dependencies and API server

```bash
uv sync                    # core deps (includes pytest, jsonschema for ontology validation tests)
uv sync --extra redis      # optional Redis client
uv sync --extra dev        # JupyterLab (for docs/notebooks/temporial_graph_rag_bridge.ipynb)
uv run uvicorn temporial_graph_rag.api.main:app --reload --host 0.0.0.0 --port 8000
uv run jupyter lab         # after uv sync --extra dev; run from repo root
```

### 7.2 Running tests (default)

From the repository root:

```bash
uv run pytest              # full suite; Neo4j integration tests skip if NEO4J_INTEGRATION_TEST is unset
uv run pytest -q           # quiet summary
uv run pytest -v           # per-test names
uv run pytest tests/test_scoring.py   # single file
uv run pytest -k isolation            # tests whose name contains "isolation" (matches multiple modules)
```

- **Unit / API tests** use `NEO4J_ENABLED=false` (or rely on FastAPI tests that stub the store) and do **not** require a database.
- **Ontology schema tests** validate `ontologies/company_events.v1.json` against [`schemas/ontology.schema.json`](../schemas/ontology.schema.json) and run in the default suite.

### 7.3 Neo4j integration tests

[`tests/test_neo4j_isolation_integration.py`](../tests/test_neo4j_isolation_integration.py) talks to a **real** Neo4j instance. Without the flag below, those tests are **skipped** (normal for CI and laptops without Docker).

1. Start Neo4j (e.g. Docker Compose) and note URI, user, password, database name.
2. Export variables (or set them in `.env` and `source` / use a tool that loads dotenv — pytest does not load `.env` automatically):

```bash
export NEO4J_INTEGRATION_TEST=1
export NEO4J_ENABLED=true
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-secret
export NEO4J_DATABASE=neo4j
```

3. Run only the integration module or the full suite:

```bash
uv run pytest tests/test_neo4j_isolation_integration.py -v
uv run pytest -v                                      # includes integration when env is set
```

The tests create and delete collections whose names look like `__itest_*__`; they must not collide with production collection names.

See also [`.env.sample`](../.env.sample) (`NEO4J_INTEGRATION_TEST`).

### 7.4 Regenerate OpenAPI JSON

After route or Pydantic model changes:

```bash
uv run python <<'PY'
import json
from pathlib import Path
from temporial_graph_rag.api.main import app
Path("docs").mkdir(exist_ok=True)
Path("docs/openapi.json").write_text(json.dumps(app.openapi(), indent=2))
PY
```
