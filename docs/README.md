# Documentation index

| Document | Purpose |
| -------- | ------- |
| [DESIGN.md](./DESIGN.md) | System design: mapping from OpenAI Temporal Agents and product enhancements to this implementation. |
| [DEVELOPER_ENHANCEMENTS.md](./DEVELOPER_ENHANCEMENTS.md) | Developer guide: multi-step retrieval, decay, ingestion, retrieval, jobs, extension points. |
| [OPENAPI.md](./OPENAPI.md) | HTTP API guide; machine-readable spec is [openapi.json](./openapi.json) (OpenAPI 3.1). |
| [ONTOLOGY.md](./ONTOLOGY.md) | Ontology JSON: taxonomy, `subevent_overrides` (impact vs decay), validation, JSON Schema. |
| [MULTI_PROJECT_OPERATING_SPEC.md](./MULTI_PROJECT_OPERATING_SPEC.md) | Project/collection tenancy model, naming conventions, persistent registry behavior, rollout guidance across domains. |
| [notebooks/temporial_graph_rag_bridge.ipynb](./notebooks/temporial_graph_rag_bridge.ipynb) | Jupyter bridge: maps reference cookbook to this repo (`LLMClient`, chunks, ontology, optional API ping). |

External references used throughout:

- **HTTP LLM contract** (upstream service this app calls): repository root [`llm_service_openapi.json`](../llm_service_openapi.json) (OpenAPI 3.1 for `/llm/*`).
- **Frozen reference** (do not rewrite for product): [`input_docs/temporal_agents.ipynb`](./input_docs/temporal_agents.ipynb) (OpenAI Temporal Agents tutorial).
- Product mapping: [`input_docs/PRODUCT_ENHANCEMENT.md`](./input_docs/PRODUCT_ENHANCEMENT.md).
