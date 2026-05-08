# Implementation Plan: Temporial Graph RAG (Approved decisions integrated)

This document translates requirements into a sequenced build plan. Baseline: **OpenAI Temporal Agents cookbook** (`temporal_agents.ipynb`). Delta: **PRODUCT_ENHANCEMENT.md**. First ontology: **CANONOCAL_EVENTS.md** → **`ontologies/company_events.v1.json`**. Ingestion: your **chunk JSON** + **per-chunk** `canonical_event` / `canonical_subevent`. Runtime: **uv**, **FastAPI**, **Neo4j**. LLM calls use your external **llm-service** (`llm_service_openapi.json` describes `/llm/*`), not OpenAI direct in app code.

---

## 0. Locked product decisions (your answers)

| Topic | Decision |
|--------|-----------|
| **Canonical labels on ingest** | Every chunk object carries **`canonical_event`** and **`canonical_subevent`**. |
| **Ontology files** | **Versioned filenames**, e.g. `company_events.v1.json` for the ontology derived from `CANONOCAL_EVENTS.md`; future domains as `economic_events.v1.json`, etc. |
| **Graph database** | **Neo4j** (no SQLite as target store). |
| **Missing `publish_date`** | Use **UTC calendar date** (`datetime.now(timezone.utc).date()`). |
| **Chunk `type` = `table`** | `content` holds table cells in English; use in extraction per mapping rules. |
| **Chunk `type` = `image`** | **Do not** use `content` for extraction (may be base64 image); use **`title_summary` only**. |
| **Extraction text (`content` mapping)** | **`text`** and **`table`**: merge **`content` + `title_summary`** for the string passed to LLM / embedder. **`image`**: **`title_summary` only**. |

---

## 1. Goals (consolidated)

| Goal | Source |
|------|--------|
| Temporal graph + RAG for market-related temporal events | README / product docs |
| Base patterns from temporal agents notebook | `temporal_agents.ipynb` (full inventory §11) |
| Financial extensions: event-first graph, impact, causality, hierarchy, decay, append-only history | `PRODUCT_ENHANCEMENT.md` |
| Controlled event types | `company_events.v1.json` (+ loader) |
| Ingest **lists of chunks** with stable IDs and provenance | Your chunk schema |
| **Per-collection** isolation (`collection_name` on all APIs and storage) | Prior requirements |
| **Pluggable ontologies** (`ontologies/`; **one ontology per collection**, no mixing) | Prior requirements |
| **uv** + **FastAPI** | Prior decisions |

---

## 2. Baseline: what `temporal_agents.ipynb` provides

Narrative + code across **238 cells** (§11). In short:

- **§3.2** Earnings **Hugging Face dataset** → **semantic chunking** (`Chunker`, Chonkie) → **`Chunk` / `Transcript`** models.
- **§3.2** **LABEL_DEFINITIONS**, **statement** extraction (`statement_extraction_prompt`, `RawStatement`, `TemporalType`, `StatementType`).
- **§3.2** **Temporal range** extraction (`date_extraction_prompt`, `RawTemporalRange`, `TemporalValidityRange`, `parse_date_str` from **`utils`**).
- **§3.2** **Predicate** enum + **PREDICATE_DEFINITIONS**, **triplet** extraction (`triplet_extraction_prompt`, `RawTriplet`, `Triplet`, `RawEntity`, `Entity`, `RawExtraction`).
- **§3.2** **`TemporalEvent`** aggregates statement + triplets + validity.
- **§3.2** **`TemporalAgent`**: `extract_statements`, `extract_temporal_range`, `extract_triplet`, `extract_transcript_events`, `_process_chunk`, `_process_statement`, embeddings for statements.
- **§3.2** **`EntityResolution`** (fuzzy / SQLite-backed via **`db_interface`**).
- **§3.2** **`InvalidationAgent`**: temporal overlap checks, embedding similarity, `invalidation_step`, `bi_directional_event_invalidation`, parallel invalidation, **`db_interface`** + **`rapidfuzz`**.
- **Persistence**: **`make_connection`**, SQLite writes in **`db_interface`** (notebook expects **`db_interface.py`** from the upstream cookbook repo).
- **§3.3** **`cb_functions.build_graph`**, **`load_db_from_hf`**, **NetworkX** visualization.
- **§4.1** **`factual_qa`**, **`trend_analysis`** tools, **`MultiStepRetriever.run`** (planner + tool loop).
- **§5 + Appendix** production guidance (scaling, indexing, TTL, concurrency, prompts).

**Gaps vs product:** triple-centric core vs **event-first** Neo4j model; no **impact / causality / decay**; chunk model and ingestion path differ; **external modules** (`db_interface`, `utils`, `cb_functions`) are not in this workspace today and must be **replaced or vendored** when adapting the notebook.

---

## 3. Contract alignment: chunks, ingest, events

### 3.1 Chunk schema (source of truth)

`chunk_id`, `content`, `type` (`text` | `table` | `image`), `doc_id`, `page`, `bundle_id`, `section_title`, `title_summary`, `publish_date`, `prev_chunk`, `next_chunk`, plus ingest-time classification fields **`canonical_event`** and **`canonical_subevent`** on each chunk object.

### 3.2 Normalization before extraction

1. **Effective `publish_date`**: if missing/null/empty → **UTC calendar date** (`datetime.now(timezone.utc).date()`).
2. **`extraction_text`** (string sent to statement/event LLM and optionally embedder):
   - `type in (text, table)`: join `content` and `title_summary` (define separator, e.g. `\n\n`, and trim empties).
   - `type == image`: `title_summary` only; **ignore** `content`.

### 3.3 Ingest payload (API / notebook demo)

- **`collection_name`** (required).
- **`ontology_id`** matching a file under `ontologies/` (e.g. `company_events.v1`); must match collection binding.
- **`chunks`**: list of chunk objects; each chunk includes **`canonical_event`** and **`canonical_subevent`** and is validated against loaded ontology.

### 3.4 Extracted graph event object

Align with `CANONOCAL_EVENTS.md` §6 where applicable (`event_id`, `normalized_subtype`, `timestamp`, `confidence`, `direction`, `magnitude`, `entities`, `source`, `ontology_version`). **`canonical_event` / `canonical_subevent`** come per chunk from ingest; LLM may still propose **`normalized_subtype`** within allowed set.

### 3.5 LLM integration contract (`llm_service_openapi.json`)

Use the external **llm-service** for all generation/embedding calls.

- **Completions endpoint:** `POST /llm/complete`
  - Request schema: `CompletionRequest` (`provider`, `messages`, optional `model`, `reasoning_effort`, `response_format`).
  - Response schema: `CompletionResponse` (`content`, optional `parsed`).
- **Embeddings endpoint:** `POST /llm/embeddings`
  - Request schema: `EmbeddingRequest` (`provider`, `input`, optional `model`, `encoding_format`, `dimensions`, `input_type`, `user`).
  - Response schema: `EmbeddingResponse`.
- **Model discovery endpoint:** `GET /llm/models` for available/default/fallback model metadata.

Implication: replace notebook code that initializes OpenAI clients directly with an internal `LLMClient` wrapper over these HTTP endpoints.

**Reconciliation with `PRODUCT_ENHANCEMENT.md` §17:** keep your chunk schema authoritative; map time/provenance only.

---

## 4. Ontology independence

### 4.1 Layout

```text
ontologies/
  company_events.v1.json    # from CANONOCAL_EVENTS.md
  …                          # future: economic_events.v1.json, etc.
```

### 4.2 Collection ↔ ontology

On collection create (or first ingest): store `collection_name` → ontology file / `ontology_id`. Reject ingest if ontology does not match. **No mixing** within a collection.

---

## 5. Storage and isolation (Neo4j)

- **Every** node and relationship carries **`collection_name`** (and **`ontology_version`** where relevant).
- Queries and indexes always filter by **`collection_name`**.
- **Append-only** event history per `PRODUCT_ENHANCEMENT.md` §7; invalidation modeled as new facts/supersession edges, not silent deletes of history.
- **Vector** store (phase E): same isolation; embeddings built from **`extraction_text`**, not raw `content` when `type == image`.

---

## 6. PRODUCT_ENHANCEMENT → work packages

| # | Gap | Planned response |
|---|-----|------------------|
| G1 | Event-centric modeling | Neo4j **Event** nodes; ingest supplies canonical labels; optional LLM for subtype/entities. |
| G2 | Impact | **Impact** nodes/edges; priors from ontology/config. |
| G3 | Probabilistic edges | `confidence` / `probability` on relationships. |
| G4 | Causality | **CAUSES** edges + optional rationale. |
| G5 | Hierarchy | `canonical_event` → `canonical_subevent` → `normalized_subtype`. |
| G6 | Time decay | Properties + retrieval scoring (later). |
| G7 | Append-only | Align invalidation with new events/edges vs notebook’s SQLite expiry semantics. |
| G8 | Query / GraphRAG | Vector + Cypher scoped by `collection_name`. |
| G9 | Chunk pipeline | Posted chunks + **`extraction_text`**; optional legacy path: HF + `Chunker` for demos only. |

---

## 7. Phased implementation steps

### Phase A — Foundation

1. `uv` project layout; dependencies (FastAPI, Pydantic v2, Neo4j driver, etc.).
2. Pydantic: `Chunk`, ingest body (`collection_name`, `ontology_id`, `chunks`), with **per-chunk** `canonical_event`/`canonical_subevent`, and **`extraction_text` / `effective_publish_date` helpers**.
3. **`ontologies/company_events.v1.json`** from `CANONOCAL_EVENTS.md`.
4. Ontology loader + validators for ingest labels.
5. Collection registry (`collection_name` → ontology).
6. Add `llm_config` module:
   - Task-level config keys (example tasks: `statement_extraction`, `temporal_range_extraction`, `triplet_or_event_extraction`, `entity_resolution_assist`, `retrieval_planner`, `answer_synthesis`, `embeddings`).
   - Per-task fields: `provider`, `model`, optional `reasoning_effort`, optional `response_format`.
   - Environment/runtime override support.
7. Build `LLMClient` HTTP adapter for `/llm/complete`, `/llm/embeddings`, `/llm/models`.
8. FastAPI: health, create collection, ingest (validation only first if needed).

### Phase B — Pipeline port (from notebook logic)

9. Port prompts/models: statements, temporal range, triplets — **parameterize** predicates/allowed types from ontology where replacing earnings-specific enums.
10. Replace direct OpenAI calls inside notebook-derived logic with `LLMClient` calls using `llm_config` per task.
11. Replace **`TemporalAgent.extract_transcript_events`** usage with **posted chunks**: drive `_process_chunk`-equivalent with **`extraction_text`** + **effective_publish_date** + **chunk metadata** (including per-chunk canonical labels) for provenance.
12. **Entity resolution**: reimplement against Neo4j (or interim in-memory) instead of SQLite `db_interface` patterns.
13. **InvalidationAgent**: port algorithms; persist outcomes as **append-only** Neo4j updates.

### Phase C — Neo4j schema + writes

14. Labels/properties: Event, Entity, Impact, CausalHypothesis (as needed), Chunk linkages, `collection_name`, timestamps.
15. Idempotent writes (`event_id`, chunk ids).

### Phase D — PRODUCT layers

16. Impact rules; 17. Causality; 18. Decay (optional pass).

### Phase E — RAG + APIs

19. Query API (scoped); 20. Admin/diagnostics.

### Phase F — Notebook

21. **Edit `temporal_agents.ipynb`**: add markdown bridging to product + ontology; swap **SQLite / `db_interface`** callouts for **Neo4j + package imports**; add cells that **ingest JSON chunks** (per-chunk `canonical_event` / `canonical_subevent`) alongside optional legacy earnings demo; replace direct OpenAI client usage with `LLMClient` + `llm_config`; retrieval section points at Neo4j-backed graph builder instead of `cb_functions`+SQLite when package is ready.

---

## 8. LLM configuration design (implementation-ready)

### 8.1 `llm_config` structure

Define a central config module/file that maps each pipeline task to model/provider settings. Example shape:

```yaml
llm:
  base_url: "http://llm-service:8001"
  timeout_seconds: 60
  tasks:
    statement_extraction:
      provider: "openai"
      model: "openai/gpt-4.1"
      reasoning_effort: "medium"
    temporal_range_extraction:
      provider: "openai"
      model: "openai/gpt-4.1-mini"
    event_or_triplet_extraction:
      provider: "openai"
      model: "openai/gpt-4.1"
      response_format:
        type: json_schema
        # schema payload here
    embeddings:
      provider: "openai"
      model: "openai/text-embedding-3-small"
```

### 8.2 Runtime behavior

- Each task call resolves config by task name.
- Requests are sent to `/llm/complete` or `/llm/embeddings`.
- Optional startup check: call `/llm/models` and warn if configured model is not listed.
- Keep fallback behavior in the external service; do not re-implement provider-level fallback in this app unless needed later.

---

## 9. Success criteria (minimal)

- Ingest for `collection_name=A` with `company_events.v1` → data visible only under A in Neo4j and vector search.
- Second collection B with no cross-leakage.
- New ontology file only via new collection (or controlled migration).
- Notebook documents dual path: **posted chunks** (production shape, with per-chunk canonical labels) vs optional **earnings Chunker** demo.
- Pipeline uses external LLM APIs (`/llm/complete`, `/llm/embeddings`) via task-specific `llm_config`.

---

## 10. First sprint artifacts

1. `ontologies/company_events.v1.json`
2. `src/.../models/chunk.py`, `ingest.py`, `extraction_text.py`
3. `src/.../ontology/loader.py`
4. `src/.../llm/config.py`, `src/.../llm/client.py`
5. `src/.../collections/registry.py`
6. `src/.../api/main.py`
7. `tests/test_isolation.py`

---

## 11. Full read: `temporal_agents.ipynb` inventory

**Totals:** **238 cells** (markdown + code). **Major notebook sections** (H1/H2 headings):

| Section | Cell range (approx.) | Role |
|---------|----------------------|------|
| **1** Executive summary, purpose, takeaways | 0–4 | Motivation, outcomes |
| **2** How to use, prerequisites | 5–10 | `pip` installs, `OPENAI_API_KEY` |
| **3** Temporal KG + Temporal Agent | 11–137 | **Core pipeline** |
| **3.1** Intro, model selection | 12–17 | Concepts, diagrams |
| **3.2** Build pipeline | 18–137 | **Data → graph** |
| 3.2.1 Load transcripts | 21–25 | HF `jlh-ibm/earnings_call` |
| 3.2.1 DB setup | 26–27 | **`make_connection`** SQLite |
| 3.2.2 Semantic chunker | 28–44 | **`Chunk`**, **`Transcript`**, **`Chunker`**, pickle load |
| 3.2.3 Foundations | 45–49 | **`LABEL_DEFINITIONS`** |
| 3.2.4 Statement extraction | 50–61 | **`TemporalType`**, **`StatementType`**, **`RawStatement`**, **`statement_extraction_prompt`** |
| 3.2.5 Temporal range | 62–71 | **`RawTemporalRange`**, **`TemporalValidityRange`**, **`date_extraction_prompt`**, **`utils.parse_date_str`** |
| 3.2.6 Triplets | 72–104 | **`Predicate`**, **`PREDICATE_DEFINITIONS`**, **`RawTriplet`**, **`Triplet`**, **`Entity`**, **`triplet_extraction_prompt`** |
| 3.2.7 TemporalEvent + TemporalAgent | 98–107 | **`TemporalEvent`**, **`TemporalAgent`** (`extract_statements`, `extract_temporal_range`, `extract_triplet`, `extract_transcript_events`, `_process_chunk`, `_process_statement`) |
| 3.2.8 Entity resolution | 108–114 | **`EntityResolution`**, **`db_interface`** |
| 3.2.9 Invalidation | 115–137 | **`event_invalidation_prompt`**, **`InvalidationAgent`** (temporal + embedding filters, parallel invalidation), pipeline driver cells, **`view_db_table`** |
| **3.3** Knowledge graphs | 138–147 | **`build_graph`**, **`load_db_from_hf`**, NetworkX stats/plots |
| **3.4** Evaluation / feature ideas | 148–154 | Extensions discussion |
| **4** Multi-step retrieval | 155–200 | **Retriever** |
| 4.1 Build retrieval agent | 160–198 | **`initial_planner`**, **`factual_qa`**, **`trend_analysis`**, schemas, **`MultiStepRetriever.run`** |
| 4.2 Evaluating retrieval | 199–200 | Metrics / golden sets |
| **5** Prototype to production | 201–205 | Ops guidance (text) |
| **Appendix** | 206–237 | Deep dive: volume, validity, indexing, TTL, concurrency, cost, safeguards, prompt optimization |

**Largest code cells (implementation depth):** **61** (statement prompt), **71** (date prompt), **98** (triplet prompt), **105** (`TemporalAgent`), **110** (`EntityResolution`), **120** (`InvalidationAgent`), **182** (`factual_qa`), **192** (`MultiStepRetriever`).

**External imports expected by notebook (not in-repo today):** **`db_interface`**, **`utils`**, **`cb_functions`**. Enhancement work **replaces SQLite + these helpers** with **Neo4j** (and project-local modules) while **preserving prompt and control-flow structure** where possible.

---

*Next step after you confirm §8.1–§8.2: start Phase A and parallel Phase F outline edits to the notebook narrative cells.*
