    # FIN-SENSE — MongoDB Schema Reference

**Database:** `finsense`  
**Environment:** MongoDB Atlas Free Tier (M0)  
**Collections:** 7  
**Source of truth:** SRS FR-A through FR-G, Backlog US-B1 through US-G8

---

## Collection Index

| Collection | Writer | Reader | Purpose |
|---|---|---|---|
| `articles` | Ingestion Pipeline | Pipeline (dedup), Audit | Persisted article metadata for URL dedup and audit trail |
| `event_clusters` | Scheduled Pipeline | Serving API, Audit Panel | Clustered events + AI extraction results |
| `daily_sentiment_history` | Nightly Batch Job | Serving API | Pre-computed EOD scores for historical chart |
| `static_ontology` | Manual seed / Admin | Serving API | Concept → sector weight + alias map |
| `audit_log` | Serving API (audit endpoints) | Admin Panel | Immutable log of every approve/correct action |

---

## 1. `articles`

Persisted article metadata. Written by ingestion pipeline. Purpose: URL deduplication and audit trail. Full content is **not** stored — pipeline uses it transiently in memory only.

```json
{
  "_id": "ObjectId (auto)",
  "article_id": "string — e.g. 'cafef_5d8a9f2'",
  "url": "string — canonical URL, unique",
  "source": "string — e.g. 'CafeF'",
  "published_at": "ISODate",
  "ingested_at": "ISODate",
  "cluster_id": "string | null — populated after clustering step"
}
```

**Indexes:**
- `url` → unique (primary dedup guard)
- `cluster_id` → for reverse-lookup from cluster → contributing articles

---

## 2. `event_clusters`

Core collection. One document per event. Written by pipeline, read by serving API and audit panel.

```json
{
  "_id": "ObjectId (auto)",
  "cluster_id": "string — e.g. 'evt_hpg_q2_2026'",
  "event_title": "string — generated summary title for the event",
  "created_at": "ISODate — timestamp of first article in cluster",
  "updated_at": "ISODate — timestamp of most recent article added",
  "centroid_embedding": "[float, float, ...]",

  "event_coverage": {
    "total_articles": "number",
    "all_urls": {
      "CafeF": ["string (url)", "..."],
      "VnExpress": ["string (url)", "..."]
    }
  },

  "aggregated_analysis": {
    "ticker_sentiments": [
      { "ticker": "string — e.g. 'HPG'", "score": "float [-1.0, 1.0] | null — null = no source at/above AI_CONFIDENCE_THRESHOLD mentioned it ('no confident read', distinct from a neutral 0)" }
    ],
    "concept_sentiments": [
      { "concept": "string — canonical enum e.g. 'STEEL'", "score": "float [-1.0, 1.0] | null — same null semantics as ticker_sentiments" }
    ],
    "needs_review": "boolean — true when no source in the cluster meets AI_CONFIDENCE_THRESHOLD; surfaces the event for human review"
  },

  "source_breakdown": [
    {
      "source": "string — e.g. 'CafeF'",
      "representative_article": {
        "url": "string",
        "published_at": "ISODate",
        "content_fed_to_ai": "string — the full_content sent to Gemini",
        "centroid_similarity": "float [-1.0, 1.0] — cosine similarity to the cluster centroid at selection time; persisted because raw embeddings are discarded once folded into the centroid, so a later pipeline run can decide whether a new candidate should replace this representative"
      },
      "ai_response": {
        "ticker_sentiments": [
          { "ticker": "string", "score": "float [-1.0, 1.0]" }
        ],
        "concept_sentiments": [
          { "concept": "string", "score": "float [-1.0, 1.0]" }
        ],
        "ai_confidence": "float [0.0, 1.0]",
        "model_version": "string — e.g. 'gemini-1.5-flash'",
        "prompt_version": "string - e.g. 'v1'",
      },
      "is_audited": "boolean — false until admin approves or corrects",
    }
  ]
}
```

**Indexes:**
- `cluster_id` → unique
- `created_at` → descending (rolling window queries, audit panel default sort)
- `aggregated_analysis.ticker_sentiments.ticker` → for ticker-level serving queries

---

## 3. `daily_sentiment_history`

Pre-computed EOD scores. Written by nightly batch job. Zero computation at serve time.

```json
{
  "_id": "ObjectId (auto)",
  "ticker": "string — e.g. 'HPG'",
  "date": "string — 'YYYY-MM-DD' format",
  "daily_sentiment_score": "float | null — null if no valid events that day",
  "closing_price": "number | null — from Price API; null if API unavailable",
  "data_points_used": "number — count of valid events used in calculation"
}
```

**Indexes:**
- `{ ticker, date }` → unique compound index (one record per ticker per day)
- `ticker` → for bulk historical queries

---

## 4. `static_ontology`

Sector/concept weight map. Manually seeded. Read by serving API for S_final calculation.  
**Mandatory human review + sign-off required before first production deployment.**

```json
{
  "_id": "ObjectId",
  "ticker": "HPG",
  "concept_weights": [
    { "concept": "STEEL", "weight": 1.0 },
    { "concept": "CONSTRUCTION_MATERIALS", "weight": 0.5 },
    { "concept": "MACRO", "weight": 0.3 }
  ]
}
```

## 5. `concept_dictionary`
```json
{
  "concept": "REAL_ESTATE",
  "aliases": ["BĐS", "BDS", "PROPERTY", "Bất động sản"]
}
```

**Indexes:**
- `aliases` → multikey index (alias lookup at serving time)

---
## 6. `audit_log`

Immutable. No application code path may delete or modify entries (US-G4).

```json
{
  "_id": "ObjectId",
  "admin_id": "string",
  "admin_name": "string",
  "action_type": "string — enum: ['approve', 'correct']",
  "cluster_id": "string",
  "source": "string",
  "old_ticker_sentiments": [ { "ticker": "HPG", "score": -0.50 } ],
  "new_ticker_sentiments": [ { "ticker": "HPG", "score": -0.20 } ],
  "old_concept_sentiments": [ { "concept": "STEEL", "score": -0.30 } ],
  "new_concept_sentiments": [ { "concept": "STEEL", "score": 0.10 } ],
  "error_type": "enum | null",
  "performed_at": "ISODate"
}
```

**Indexes:**
- `cluster_id` → for panel query by event
- `performed_at` → descending (time-range filter US-G6)
- `error_type` → for error taxonomy grouping (US-G5)

---

## Atlas Setup Checklist

### Step 1 — Create Cluster
1. Atlas dashboard → **Build a Database** → **M0 Free** (do NOT select M2/M5)
2. Provider: AWS, Region: Singapore (`ap-southeast-1`) — lowest latency from HCMC
3. Cluster name: `finsense-cluster`

### Step 2 — Database Access
1. **Database Access** → **Add New Database User**
2. Username: `finsense-app`, Password: generate strong password → save to `.env`
3. Role: **Read and write to any database**
4. Add a second user `finsense-readonly` with **Read any database** role (for evaluation scripts)

### Step 3 — Network Access
1. **Network Access** → **Add IP Address**
2. For development: add your current IP
3. Add `0.0.0.0/0` temporarily for GitHub Actions (or use Atlas fixed IP allowlist when you deploy)
4. **Note:** In production, lock this down to your Render server IP + GitHub Actions IP ranges

### Step 4 — Get Connection String
1. **Connect** → **Drivers** → Python → copy the URI
2. Format: `mongodb+srv://finsense-app:<password>@finsense-cluster.xxxxx.mongodb.net/`
3. Add to `.env` as `MONGODB_URI=...` — never commit this

### Step 5 — Create Collections
Run this init script after connecting (see `backend/scripts/init_db.py` below):

```
Database: finsense
Collections to create:
  - articles
  - event_clusters
  - daily_sentiment_history
  - static_ontology
  - audit_log
```

---

## Init Script

Save as `backend/scripts/init_db.py` in the repo:

```python
