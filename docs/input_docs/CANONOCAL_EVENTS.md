# Financial Event Ontology (Production Ready)

## 1. Objective

This document defines the **standardized financial event ontology** for the Temporal Financial Graph System.

It is derived from real-world exchange disclosures and normalized for:

* Event extraction (LLM)
* Graph consistency (Neo4j)
* Impact modeling (ML + rules)
* Agent reasoning

---

## 2. Design Principles

* Strict controlled vocabulary (no free-form types)
* Hierarchical (Event → SubEvent → Subtype)
* Financially meaningful (mapped to impact)
* ML-friendly (categorical encoding)
* Compatible with OpenAI Temporal Agents

---

## 3. Event Hierarchy

```
Level 1 → canonical_event
Level 2 → canonical_subevent
Level 3 → normalized_subtype
```

---

## 4. Canonical Event Types (Level 1)

```
EARNINGS_FINANCIALS
FUND_RAISE_CAPITAL
RESTRUCTURING
MANAGEMENT_CHANGE
BOARD_MEETING
MARKET_ACTION
BUSINESS_UPDATE
LEGAL_REGULATORY
INSIDER_TRADING
CREDIT_RATING
CORPORATE_ACTION_GENERAL
CSR_ESR
OTHER
```

---

## 5. Subtypes (Level 2 + 3 Combined)

### 5.1 EARNINGS_FINANCIALS

```
RESULTS
EARNINGS
INVESTOR_MEET
DELAY
AUDIT
```

---

### 5.2 FUND_RAISE_CAPITAL

```
ALLOTMENT
ISSUANCE
RIGHTS_ISSUE
PREFERENTIAL
QIP
DEBENTURES
REDEMPTION
FUND_USE
CREDIT_RATING
ANNOUNCEMENT
```

---

### 5.3 RESTRUCTURING

```
ACQUISITION
MERGER
TAKEOVER
DEMERGER
SALE
BUSINESS_SALE
DIVERSIFY
NCLT
EXTINCTION
LIQUIDATION
```

---

### 5.4 MANAGEMENT_CHANGE

```
APPOINTMENT
RESIGN
RETIRE
HIRE
FIRE
DIRECTOR
AUDITOR_RESIGN
```

---

### 5.5 BOARD_MEETING

```
SHAREHOLDERS_MEETING
COMMITTEE_MEETING
EXTRA_ORDINARY_MEETING
OUTCOME
INTIMATION
```

---

### 5.6 MARKET_ACTION

```
DIVIDEND
BUYBACK
BUYBACK_END
SPLIT
BONUS
RECORD_DATE
OPEN_OFFER
DELISTING
SUSPENSION
OFS
ANNOUNCEMENT
VOLUME
PRICE_MOVEMENT
```

---

### 5.7 BUSINESS_UPDATE

```
CONTRACT_WIN
CONTRACT_LOSS
CAPACITY_ADDITION
CAPACITY_REDUCTION
PRODUCT_LAUNCH
INCORPORATION
OPERATIONS_START
OPERATIONS_DISRUPTION
EXPANSION
AGREEMENT
```

---

### 5.8 LEGAL_REGULATORY

```
INVESTIGATION
ACTION_TAKEN
COMPLIANCE
LITIGATION
REGULATORY_APPROVAL
DISCLOSURE
```

---

### 5.9 INSIDER_TRADING

```
TRADING_WINDOW
DISCLOSURE
RELATED_PARTY_TRANSACTION
INSIDER_ACTIVITY
```

---

### 5.10 CREDIT_RATING

```
RATING_UPDATE
RATING_NEW
RATING_REVISION
```

---

### 5.11 CORPORATE_ACTION_GENERAL

```
ADDENDUM
CORRIGENDUM
RECORD_DATE
GENERAL_UPDATE
```

---

### 5.12 CSR_ESR

```
ESR
```

---

## 6. Event Object Schema

```json
{
  "event_id": "hash",
  "canonical_event": "EARNINGS_FINANCIALS",
  "canonical_subevent": "RESULTS",
  "normalized_subtype": "RESULTS",

  "timestamp": "2026-01-10T10:00:00Z",
  "confidence": 0.92,

  "direction": "positive",
  "magnitude": "medium",

  "entities": [
    {
      "name": "Infosys",
      "type": "Company",
      "ticker": "INFY"
    }
  ],

  "source": {
    "doc_id": "doc123",
    "chunk_id": "chunk456",
    "source_type": "news"
  },

  "ontology_version": "v1.0"
}
```

---

## 7. Validation Rules

* Only predefined canonical_event allowed
* Only predefined normalized_subtype allowed
* No new categories allowed from LLM

Fallback:

```
Unknown → map_to_closest()
```

---

## 8. Usage in System

### Extraction Layer

* LLM must output only valid ontology values

### Graph Layer

* canonical_event → Event.type
* normalized_subtype → Event.subtype

### Impact Engine

```python
IMPACT_PRIORS = {
  "RESULTS": {"sr": 0.02},
  "ACQUISITION": {"sr": 0.015},
  "DIVIDEND": {"sr": 0.01},
  "RESIGN": {"sr": -0.02}
}
```

---

## 9. Rules for OTHER

Use ONLY when:

* No financial impact
* No structural change
* No causal relevance

Otherwise:

```
Force map to closest category
```

---

## 10. Versioning

* ontology_version = "v1.0"
* Future changes must be versioned

---

## 11. Key Guarantees

* Consistent graph structure
* Clean event extraction
* Reliable impact modeling
* Strong agent reasoning foundation
