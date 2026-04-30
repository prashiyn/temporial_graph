# Adapting OpenAI Temporal Agents → Financial Temporal Graph System

## 1. Objective

This document maps the OpenAI Temporal Agents prototype into a **production-grade financial temporal graph system** tailored for:

* Event-driven financial data
* Probabilistic impact modeling
* Causal reasoning for stock movements

---

## 2. What OpenAI Temporal Agents Provide

### Core Capabilities

* Temporal triples (subject–relation–object + time)
* Validity intervals (valid_from, valid_to)
* Incremental graph updates
* Agent-based reasoning over time

### Conceptual Model

```
(Entity) — (Relation) — (Entity)
   + time
```

---

## 3. Gaps for Financial Use Case

### Missing Components

1. **Event-Centric Modeling**

   * OpenAI uses triples
   * Finance requires events as first-class nodes

2. **Impact Modeling**

   * No concept of market reaction
   * No linkage to price movement

3. **Probabilistic Relationships**

   * Financial systems are uncertain
   * Requires probabilities + confidence

4. **Causality Layer**

   * Only temporal ordering exists
   * No cause-effect reasoning

5. **Event Hierarchy**

   * No coarse vs fine events

6. **Time Decay**

   * No modeling of fading impact

---

## 4. Target System Extension

We extend the model from:

```
(S, P, O, time)
```

To:

```
(Event) → (Impact) → (Company / Price)
+ probability
+ decay
+ causality
```

---

## 5. Modified Data Model

### 5.1 Event-Centric Graph

Replace triple-centric design with:

* Event nodes
* Entity nodes
* Derived nodes (Impact, CausalHypothesis)

---

### 5.2 Temporal Financial Quadruple

```
Subject: Event
Relation: IMPACTS / CAUSES
Object: Company / Event / Price
Time: event_time
Attributes:
  - probability
  - impact magnitude
  - decay
```

---

### 5.3 Additional Nodes

* Impact
* CausalHypothesis
* PricePoint
* SentimentSnapshot

---

## 6. Ingestion Modifications

### OpenAI Flow

```
Text → Extract triples → Update graph
```

### Modified Flow

```
Text → Extract entities
     → Extract events (fine-grained)
     → Build event hierarchy
     → Compute impact (rule + ML)
     → Write graph
```

---

## 7. Graph Update Strategy

### OpenAI

* Update triples with validity intervals

### Modified

* Append-only event log
* Add new relationships
* Maintain temporal edges
* Never overwrite history

---

## 8. Causality Extension

Add explicit edges:

```
Event A → CAUSES → Event B
Event A → CAUSES → Price Movement
```

With:

* probability
* reasoning

---

## 9. Impact Layer (New)

Each event generates:

* short-term return
* medium-term return
* probability
* decay

---

## 10. Time Modeling

### Corporate Events

* event_time
* valid_from
* valid_to

### News

* event_time only

---

## 11. Query Layer Changes

### OpenAI

* Retrieve facts over time

### Modified

* Explain stock movement
* Track sentiment trends
* Detect structural changes

---

## 12. Agent Integration

### OpenAI Agents

* Reason over temporal facts

### Financial Agents

* Combine:

  * graph traversal
  * impact signals
  * causal reasoning

---

## 13. Final Architecture

```
OpenAI Temporal Agent (Base)
        ↓
Event Extraction Layer
        ↓
Temporal Financial Graph (Neo4j)
        ↓
Impact + Causality Layer
        ↓
GraphRAG
        ↓
Agentic Trading System
```

---

## 14. Key Design Principles

* Event-first modeling
* Probabilistic relationships
* Time decay
* Append-only graph
* Hybrid reasoning (graph + vector + ML)

---

## 15. Implementation Strategy

### Phase 1

* Use OpenAI temporal extraction for base triples

### Phase 2

* Convert triples → events

### Phase 3

* Add impact + causality

### Phase 4

* Integrate with agent layer

---

## 16. Implementation Mapping (OpenAI → Financial System)

### 16.1 Concept Mapping

| OpenAI Temporal Agents | Financial System Equivalent          |
| ---------------------- | ------------------------------------ |
| Triple (S, P, O)       | Event Node + Relationships           |
| valid_from / valid_to  | event_time / validity                |
| Entity                 | Company / Person / Instrument        |
| Relation               | Causal / Impact / Structural Edge    |
| Memory                 | Temporal Event Graph                 |
| Agent Reasoning        | GraphRAG + Impact + Causal Reasoning |

---

### 16.2 Pipeline Mapping

#### OpenAI

```
Text → Chunk → Extract Triples → Update Graph → Agent
```

#### Modified System

```
Chunk (JSON) → Event Extraction → Normalization → Impact Computation → Graph Write → Agent
```

---

## 17. Chunker Output Contract (CRITICAL)

This system assumes **chunking is already implemented**.

All downstream systems will consume **chunk JSON in this format**.

### 17.1 Design Principles

* Must align with OpenAI temporal ingestion
* Must support deterministic extraction
* Must carry metadata for time + provenance

---

### 17.2 Chunk Schema

```json
{
  "chunk_id": "uuid",
  "doc_id": "source_document_id",
  "source_type": "news | filing | research",
  "source_name": "Reuters",
  "timestamp": "2026-01-10T10:00:00Z",
  "ticker_hint": "INFY",
  "content": "text chunk",
  "metadata": {
    "language": "en",
    "region": "IN",
    "confidence": 1.0
  }
}
```

---

### 17.3 Alignment with OpenAI Notebook

OpenAI expects:

* text input
* timestamp
* incremental updates

This schema preserves:

| OpenAI Requirement | Field               |
| ------------------ | ------------------- |
| Text               | content             |
| Time               | timestamp           |
| Source tracking    | doc_id, source_name |
| Context            | metadata            |

---

### 17.4 Deterministic ID Strategy

```text
chunk_id = hash(doc_id + content + timestamp)
```

Ensures:

* idempotency
* deduplication

---

## 18. Event Extraction Adaptation (Code-Level)

### Replace OpenAI Triple Extraction

#### Original

```
(S, P, O, time)
```

#### New

```
Chunk → EventOut[]
```

---

### 18.1 Extraction Function (Pseudo)

```python
def extract_events_from_chunk(chunk):
    text = chunk["content"]
    timestamp = chunk["timestamp"]

    events = llm_extract(text)

    for e in events:
        e["timestamp"] = timestamp

    return events
```

---

### 18.2 Normalization Layer

```python
def normalize_event(e):
    e["type"] = map_type(e["type"])
    e["subtype"] = map_subtype(e["subtype"])
    return e
```

---

## 19. Graph Update Adaptation

### OpenAI

```
Update triple with validity
```

### Modified

```
Append Event
→ Link Entities
→ Add Impact
→ Add Causality
```

---

## 20. Minimal Working Flow (End-to-End)

```text
Chunk Input
 → Event Extraction
 → Normalize
 → Generate Event ID
 → Write Event (Neo4j)
 → Compute Impact
 → Write Impact
 → Link Price
 → Update Causal Graph
```

---

## 21. Key Enhancements Over OpenAI

| Capability          | OpenAI  | This System |
| ------------------- | ------- | ----------- |
| Temporal tracking   | Yes     | Yes         |
| Event modeling      | No      | Yes         |
| Impact modeling     | No      | Yes         |
| Causality           | Limited | Explicit    |
| Market linkage      | No      | Yes         |
| Agentic decisioning | Basic   | Advanced    |

---

## 22. Updated Conclusion

OpenAI Temporal Agents provide a **strong temporal reasoning base**, but this system extends it into:

> A **Temporal + Probabilistic + Causal Financial Intelligence Engine**

Key additions:

* Event-centric modeling
* Impact computation
* Time decay
* Causal graph
* Chunk-driven ingestion pipeline

This enables direct use in **agentic trading systems**.
