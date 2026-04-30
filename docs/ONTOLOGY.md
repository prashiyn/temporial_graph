# Ontology definition guide

This document explains how **ontology JSON files** drive ingestion validation, impact priors, triplet predicates, snapshot supersession windows, and **retrieval decay thresholds**. It complements [DESIGN.md](./DESIGN.md) and [DEVELOPER_ENHANCEMENTS.md](./DEVELOPER_ENHANCEMENTS.md).

---

## 1. File location and naming

- Ontologies live under **`ontologies/`** at the repository root.
- The file name must be **`{ontology_id}.json`**, where `ontology_id` matches the `ontology_id` field inside the JSON (e.g. `company_events.v1.json` for `"ontology_id": "company_events.v1"`).
- Collections reference an ontology by **`ontology_id`**; the service loads `ontologies/{ontology_id}.json` via `load_ontology()`.

---

## 2. What is a “subevent”?

The taxonomy has two levels:

| Level | JSON field | Role |
| ----- | ---------- | ---- |
| **Canonical event** | Key in `canonical_events` | Coarse bucket (e.g. `EARNINGS_FINANCIALS`, `LEGAL_REGULATORY`). |
| **Canonical subevent** | Value in the array for that key | Fine-grained label (e.g. `RESULTS`, `LITIGATION`). |

Every ingested chunk must declare a valid **`(canonical_event, canonical_subevent)`** pair: the subevent must appear in the array for that event. This is enforced by `Ontology.validate_pair()`.

**Reference example:** [`ontologies/company_events.v1.json`](../ontologies/company_events.v1.json).

---

## 3. The term `subevent_overrides` (two different blocks)

The string **`subevent_overrides`** appears in **two separate places** in the ontology. They are **not** interchangeable.

### 3.1 `impact_priors.subevent_overrides`

- **Keys:** `canonical_subevent` strings (e.g. `RESULTS`, `DIVIDEND`), **not** full event names.
- **Values:** Partial **impact prior** objects (direction, magnitude, probability, return bps, `decay_half_life_days`, etc.).
- **Merge order** (implemented in `Ontology.get_impact_prior`):

  ```text
  default
    → impact_priors.event_overrides[canonical_event]
    → impact_priors.subevent_overrides[canonical_subevent]
  ```

Later layers override earlier ones for each field present.

**Purpose:** Give **finer-grained** market priors than event-level overrides. Example: under `EARNINGS_FINANCIALS`, `RESULTS` may be strongly positive while another subevent under the same event stays closer to the event default.

### 3.2 `decay_retrieval.subevent_overrides`

- **Keys:** Same idea — `canonical_subevent` labels that must exist somewhere under `canonical_events`.
- **Values:** Objects with **`decay_weight_threshold`** only (strictly between 0 and 1; see JSON Schema).
- **Merge order** (implemented in `Ontology.get_decay_weight_threshold`):

  ```text
  decay_retrieval.default.decay_weight_threshold
    → decay_retrieval.subevent_overrides[canonical_subevent].decay_weight_threshold
  ```

**Purpose:** Control **how aggressively old content is dropped** for that subevent at retrieval time and in the weekly decay-suppression job. A **higher** threshold keeps less old content (stricter); a **lower** threshold is more permissive.

**Summary table**

| Location | Keyed by | Affects |
| -------- | -------- | ------- |
| `impact_priors.subevent_overrides` | `canonical_subevent` | Impact scoring + persisted `decay_half_life_days` on snapshots (from merged prior) |
| `decay_retrieval.subevent_overrides` | `canonical_subevent` | Minimum **decay weight** to retain in search/RAG and optional suppression marking |

---

## 4. `event_overrides` (impact vs snapshot supersession)

### 4.1 `impact_priors.event_overrides`

- **Keys:** `canonical_event` (must be a key in `canonical_events`).
- **Values:** Partial impact prior patches merged **after** `default` and **before** `subevent_overrides`.

Use this when an entire event family shares priors (e.g. all `LEGAL_REGULATORY` subevents skew negative unless a subevent override refines further).

### 4.2 `snapshot_embedding_supersession.event_overrides`

- **Keys:** `canonical_event`.
- **Values:** `{ "publish_date_max_hours_apart": <hours> }` — max absolute difference in publish time (hours) when considering embedding-based snapshot supersession for that event type.
- **`default`** under `snapshot_embedding_supersession` sets the baseline; per-event overrides replace it for matching events.

This is **independent** of impact priors; it only tunes **near-duplicate snapshot** behavior.

---

## 5. `predicate_definitions`

- Map **predicate name → short definition** (upper snake case names, e.g. `RELATES_TO`).
- Used in LLM prompts for event/triplet extraction and in `_normalize_predicates` to restrict unknown predicates to `RELATES_TO`.
- **Best practice:** Always include **`RELATES_TO`** as the generic fallback (semantic validator warns if it is missing).

---

## 6. `decay_retrieval.default`

- **`decay_weight_threshold`:** Number in (0, 1]. Snapshots with computed `decay_weight` **below** this value are excluded from decay-filtered retrieval and can be marked by the weekly job (`retrieval_decay_suppressed_at`).
- If the whole `decay_retrieval` section is omitted, the loader treats it as `{}` and code falls back to **0.1** for the threshold.

---

## 7. How the runtime uses the ontology

| Subsystem | Ontology data used |
| --------- | ------------------- |
| Ingest API | `validate_pair`, `predicate_definitions` |
| `ChunkProcessor` / scoring | `get_impact_prior` → direction, magnitude, probability, bps, **decay_half_life_days** |
| Neo4j persist | `ontology_id`, `ontology_version`, snapshot supersession window hours |
| RAG + retrieval tools | `get_decay_weight_threshold`, half-life from stored snapshot / prior |
| Weekly decay job | `get_decay_weight_threshold` per snapshot’s `canonical_subevent` |

---

## 8. Validation: JSON Schema + semantics

### 8.1 JSON Schema

- **Path:** [`schemas/ontology.schema.json`](../schemas/ontology.schema.json)  
- **Draft:** 2020-12  
- Validates structure, types, enums (e.g. impact `direction` / `magnitude`), numeric ranges (`decay_weight_threshold` in (0,1], `publish_date_max_hours_apart` in (0, 8760], etc.), and **rejects unknown top-level keys** (`additionalProperties: false` on the root).

### 8.2 Semantic checks (taxonomy consistency)

Implemented in `temporial_graph_rag.ontology.schema_validation.semantic_validate`:

- Every key in **`impact_priors.event_overrides`** must be a **`canonical_events`** key.
- Every key in **`impact_priors.subevent_overrides`** must appear in **some** `canonical_events[...]` array.
- Same subevent-key rule for **`decay_retrieval.subevent_overrides`**.
- Every key in **`snapshot_embedding_supersession.event_overrides`** must be a **`canonical_events`** key.
- Warning-style recommendation: **`RELATES_TO`** should exist in `predicate_definitions`.

**Note:** The same subevent string may legally appear under **multiple** canonical events (e.g. shared labels). Overrides keyed by subevent apply **by that string globally** whenever that `canonical_subevent` appears on a chunk—regardless of which parent event it was filed under. Design overrides accordingly.

### 8.3 Commands

```bash
# Combined JSON Schema + semantic validation
uv run python -m temporial_graph_rag.ontology.schema_validation ontologies/company_events.v1.json
```

Programmatic use:

```python
from pathlib import Path
from temporial_graph_rag.ontology import validate_ontology_file

errors = validate_ontology_file(Path("ontologies/my_ontology.json"))
assert not errors, errors
```

### 8.4 Tests

[`tests/test_ontology_schema.py`](../tests/test_ontology_schema.py) validates the bundled company ontology and regression cases for schema/semantic failures.

---

## 9. Authoring a new ontology (checklist)

1. Copy `company_events.v1.json` as a template or start from an empty object matching the schema.
2. Define **`canonical_events`** first (single source of truth for valid pairs).
3. Fill **`predicate_definitions`**; include **`RELATES_TO`**.
4. Set **`impact_priors.default`**, then optional **`event_overrides`** / **`subevent_overrides`**.
5. Add **`snapshot_embedding_supersession`** if you need non-default supersession windows.
6. Add **`decay_retrieval`** with `default.decay_weight_threshold` and optional per-subevent overrides.
7. Run **`python -m temporial_graph_rag.ontology.schema_validation`** on the file.
8. Register collections with the new **`ontology_id`** and run ingest smoke tests.

---

## 10. Related code

| Module | Responsibility |
| ------ | ---------------- |
| `temporial_graph_rag/ontology/loader.py` | `Ontology`, `load_ontology`, merges for priors/thresholds/windows |
| `temporial_graph_rag/ontology/schema_validation.py` | Schema + semantic validation, CLI |
| `temporial_graph_rag/pipeline/scoring.py` | Consumes merged impact prior |
| `temporial_graph_rag/retrieval/decay.py` | Uses `get_decay_weight_threshold` and half-life |

For canonical event **naming and taxonomy inspiration**, see [`docs/input_docs/CANONOCAL_EVENTS.md`](./input_docs/CANONOCAL_EVENTS.md) (reference material; the ontology file is authoritative for the running system).
