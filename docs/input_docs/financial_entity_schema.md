# Financial Graph Entity Schema (Production Ready)

## 1. Company Entity
**Fields:**
- id, name, ticker, aliases  
- sector, industry, country, exchange  
- market_cap, market_cap_bucket  
- listing_date, is_active  
- created_at, updated_at  

**Derived:**
- volatility_bucket, beta, avg_volume  
- sentiment_score, risk_score  

---

## 2. Person Entity
- id, name, role  
- company, start_date, end_date, is_active  

---

## 3. Institution Entity
- id, name, type, category, country  

---

## 4. Sector Entity
- name, code  
- macro_sensitivity (interest_rate, inflation)  

---

## 5. Event Entity
- event_id, canonical_event, canonical_subevent, normalized_subtype  
- timestamp, event_time  
- confidence, direction, magnitude  
- description, source_type, ontology_version  
- created_at  

**Derived:**
- recency_score, event_weight, event_cluster_id  

---

## 6. News Entity
- id, source, author  
- timestamp, headline, content  
- sentiment, sentiment_label  
- url, language, chunk_count  

---

## 7. PricePoint Entity
- timestamp, open, close, return  
- volume, volatility  

---

## 8. Impact Entity
- id, short_term_return, medium_term_return  
- probability, decay_lambda  
- time_horizon, model_source, created_at  

**Derived:**
- decayed_value, impact_score  

---

## 9. CausalHypothesis Entity
- id, probability, confidence  
- reasoning, model_source, created_at  

---

## 10. Relationship Properties
- event_time, valid_from, valid_to  
- confidence, probability  

---

## 11. Common Metadata (All Entities)
- created_at, updated_at  
- source, version  
