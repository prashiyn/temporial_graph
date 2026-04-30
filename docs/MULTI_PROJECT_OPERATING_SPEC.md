# Multi-Project Operating Spec

Audience: product engineers, platform operators, and Cursor/Codex agents working on this repository.

This spec defines how to run this system across many analysis "projects" (stocks, portfolios, real-estate entities) using the current architecture.

---

## 1) Core concept: project = collection

In this codebase, the tenancy/isolation unit is **`collection_name`**.

- A collection is a logical project scope.
- Every collection is bound to one ontology (`ontology_id`).
- Graph writes and retrieval queries are scoped by `collection_name`.

Use this as the canonical mental model:

```text
project -> collection_name -> ontology_id -> scoped graph + retrieval
```

---

## 2) Project taxonomy and naming convention

Use deterministic names so humans and agents can reason about ownership and scope:

```text
<domain>:<market_or_region>:<instrument_or_entity>
```

Examples:

- `stocks:nse:INFY`
- `stocks:nasdaq:MSFT`
- `realestate:in:blr-office-park`
- `realestate:us:reit-o`

Rules:

1. Lowercase for domain/market; uppercase ticker where applicable.
2. Do not reuse a collection for unrelated entities.
3. Prefer one company/instrument per collection for high precision retrieval.

---

## 3) Ontology binding rules

Each collection binds to exactly one ontology.

- Stock projects can use `company_events.v1`.
- Real-estate projects should use a domain ontology (e.g. `real_estate_events.v1`) once created.

Binding invariants (enforced by registry + API):

1. Collection must exist before ingest.
2. Ingest `ontology_id` must match collection binding.
3. Chunk `canonical_event`/`canonical_subevent` must validate against bound ontology.

---

## 4) Storage model and persistence behavior

### 4.1 Persistent collection registry (implemented)

The registry now supports two modes:

- **Neo4j-enabled app** -> `Neo4jCollectionRegistry` (persistent `RagCollection` nodes)
- **Neo4j-disabled app/tests** -> in-memory `CollectionRegistry`

Selection happens during FastAPI lifespan startup in `api/main.py`.

### 4.2 Registry semantics

Create behavior:

- `create(collection_name, ontology_id)` is idempotent when ontology matches existing.
- If the same collection exists with a different ontology, creation fails with conflict semantics.

List/get behavior:

- `GET /v1/collections` reflects persistent `RagCollection` data when Neo4j is enabled.

---

## 5) Recommended operating patterns

### Pattern A: one stock per collection (recommended default)

Use when you want precise per-company answers and simpler governance.

Pros:

- Strong relevance and low retrieval noise
- Easy ontology upgrades per project
- Clear ownership and auditing

### Pattern B: thematic portfolio collection

Use only for explicit cross-instrument analysis (sector, basket, thematic).

Guardrails:

- Keep entity-rich metadata in chunks.
- Add query filters (event types, dates, entities) to control noise.

### Pattern C: cross-collection orchestrated query

Preferred for portfolio-wide answers while retaining project isolation:

1. Fan out same query to multiple collections.
2. Collect top scoped evidence per collection.
3. Merge/rank with domain-specific policy.

This can be implemented as an orchestration layer without collapsing everything into one collection.

---

## 6) Domain rollout plan

### Stocks (today)

- Collection per ticker/company.
- Ontology: `company_events.v1`.
- Ingest: filings, disclosures, news chunks with per-chunk canonical labels.

### Real estate (next)

1. Author `real_estate_events.v1.json` under `ontologies/`.
2. Validate with schema + semantic validator.
3. Create collections with `realestate:*` naming.
4. Ingest domain documents with matching canonical labels.

---

## 7) Agent-readable implementation checklist

When implementing features that touch tenancy:

1. Ensure all writes include `collection_name`.
2. Ensure all reads are filtered by `collection_name`.
3. Keep `collection_name -> ontology_id` immutable unless an explicit migration feature is added.
4. For new APIs, always include `collection_name` in path or payload and validate existence.
5. Add tests for mismatched ontology binding and cross-collection leakage.

When changing registry behavior:

1. Keep in-memory fallback for `NEO4J_ENABLED=false`.
2. Avoid destructive global clears in production code paths.
3. Preserve current error semantics (`404` missing collection, `409` create conflict, `400` validation mismatch).

---

## 8) Migration and lifecycle guidance

### New project

1. Pick a stable `collection_name`.
2. Create collection with target ontology.
3. Start ingestion.
4. Verify via `GET /v1/collections` and scoped searches.

### Ontology version upgrade (safe path)

1. Create new collection with new ontology version (e.g. `stocks:nse:INFY:v2` naming extension if needed).
2. Re-ingest selected corpus.
3. Compare retrieval quality.
4. Switch consumers when ready.

Avoid rebinding an existing active collection to a new ontology in place.

---

## 9) Out-of-scope / future enhancements

Not part of this spec's implemented scope:

- Fine-grained row-level ACLs per user/team
- Persistent authn/authz policy around collections
- Cross-collection ranking service in core API
- Automated ontology migration tooling

These can be layered on top of the current collection tenancy.

