# Codebase Guide — FIN-SENSE

This document tells you where your code belongs based on what you're working on.
Read this before touching anything in the repo.

---

## Top-level map

```
backend/       Python backend — pipeline and API
frontend/      Next.js frontend — public dashboard and admin panel
evaluation/    Evaluation harness and calibration sweeps
docs/          Architecture, schema, onboarding, ADRs, OpenAPI spec
scripts/       One-off ops scripts (DB init, seeding, validation)
.github/       CI/CD workflows and branch protection rules
```

---

## Backend

### `backend/core/` — shared layer

Imported by both the API and the pipeline. Do not put anything here that is
specific to only one of them.

```
config.py           Environment variable loading and validation
database.py         MongoDB connection (sync, pymongo) — pipeline
database_async.py   MongoDB connection (async, motor) — API
enums.py            Ticker and Concept enums — frozen to the current VN30 basket
exception.py        Base exception classes
formulas.py         S_final, recency decay, confidence weighting — shared scoring math
log.py              Shared log formatter and configuration
text_utils.py       Shared text helpers
schemas/            Shared Pydantic models, one file per domain
  article.py            Article contract (rss → cluster)
  event_cluster.py      event_clusters document contract
  sentiment.py          TickerSentiment, ConceptSentiment, AIResponse, AggregatedAnalysis
```

**Schemas rule:** define a model once. `event_cluster.py` imports the sentiment
models rather than redeclaring them. If the same class name appears in two
files, one of them is wrong.

### `backend/api/` — serving API

FastAPI app. Reads from MongoDB. No AI calls. No pipeline imports.

```
main.py                        App entrypoint, router registration
features/                      One folder per API domain
  auth/                        Login, JWT issuance
  audit/                       Admin audit queue, corrections, guard
  dashboard/                   Market gauge and top tickers
  events/                      Trending event list
  history/                     Per-ticker daily sentiment history
  ticker/                      Ticker detail, score aggregation
  internal/                    Internal/health endpoints
external/
  price/                       Price API adapter (placeholder until wired)
tests/
  unit/                        Unit tests per feature
  integration/                 Route-level integration tests
  e2e/                         End-to-end flows (e.g. admin login)
```

**Adding a new API endpoint:** create a new folder under `features/` with
`router.py`, `schemas.py`, `service.py`. Register the router in `main.py`.

### `backend/pipeline/` — scheduled pipeline

Runs on a cron via GitHub Actions. Writes to MongoDB. Never calls the API.

Pipeline execution order: **rss → cluster → scraper → extract → aggregate**

Clustering runs before scraping on purpose. Only the centroid article of each
cluster gets its full body scraped, so scraping after clustering avoids
fetching bodies we will never send to the LLM. `content_fed_to_ai` is therefore
`None` at clustering time and populated by the scraper stage.

`docs/PIPELINE.md` documents every stage in detail — read it before changing
stage internals; this section only covers where files belong.

```
main.py                        Pipeline entrypoint, stage orchestration — run_pipeline()
stages/
  rss/                         Stage 1 — RSS ingestion
    rss_fetcher.py             Fetches and parses RSS feeds from all sources
    url_normalizer.py          Normalizes URLs before dedup check
    filter.py                  Dedup against MongoDB + relevance filter on title/summary
    stage.py                   Stage coordinator — run_rss()
  cluster/                     Stage 2 — Embedding and clustering
    embedder.py                Generates sentence embeddings
    clustering.py              Incremental cosine clustering of embedded articles
    centroid.py                Calculates and updates cluster centroids
    stage.py                   Stage coordinator — run_cluster()
  scraper/                     Stage 3 — Full body scraping of centroid articles
    source_client.py           Routes to the correct scraper adapter
    adapters/
      cafef.py                 CafeF HTTP fetch + body extraction
      vnexpress.py             VnExpress HTTP fetch + body extraction
    stage.py                   Stage coordinator — run_scraper()
  extract/                     Stage 4 — LLM sentiment extraction
    client.py                  Gemini binding, request schema, invoke_llm()
    prompt_builder.py          Loads the active prompt version from config
    extractor.py               Orchestrates prompt → invoke → validate → AIResponse
    prompts/                   Versioned prompt files — never edit existing files
      v1.txt
      v2.txt
      v3.txt
    stage.py                   Stage coordinator — run_extract()
  aggregate/                   Stage 5 — event-level aggregation
    event_aggregator.py        Confidence-weighted average across a cluster's sources
    stage.py                   Stage coordinator — run_aggregate()
eod_batch/                     Separate cron entrypoint — NOT part of run_pipeline, so not a stage
  eod_batch.py                 Rolls daily sentiment into daily_sentiment_history (ICT days)
  real_price.py                VNDirect closing-price adapter
lexicon/                       JSON config files — pipeline-only
  vietnam_financial_lexicon.json   Sentiment terms, abbreviations, aliases (currently unused)
  concept_dictionary.json          Concept alias resolution (currently unused)
  relevance_keywords.json          Keywords used by relevance filter in rss/filter.py
tests/
  unit/                        Unit tests per stage — fully mocked, no network
  integration/                 Full pipeline integration test — mongomock, no network
  live/                        Real Gemini API calls — costs quota, excluded by default
```

`static_ontology.json` and `ticker_metadata.json` live in `backend/core/data/`, **not** in
`pipeline/lexicon/` — they are shared with the API, and nothing under `pipeline/` may be.

**Stage structure convention:** every stage has helper modules plus a
`stage.py` holding the coordinator function (`run_<stage>`). The coordinator is
the only thing that touches MongoDB; helpers stay pure and testable. Stages
hand off to each other through MongoDB, never in memory — that is what makes
the pipeline idempotent and checkpointable.

**Extract stage layering:**
```
prompt_builder.build_prompt()  → (prompt, prompt_version)
client.invoke_llm()            → (raw dict, model_version)
extractor.extract_from_text()  → ExtractionResult(ai_response | failure_type)
stage.run_extract()            → reads clusters, writes ai_response to MongoDB
```
`client.py` knows only about the provider. It does not build prompts and does
not construct persistence models. `extractor.py` composes the two and owns
failure handling. Invalid entries in the LLM response are logged and dropped;
one out-of-vocabulary term must never cost the whole article.

**Adding a new news source:** add an adapter in `stages/scraper/adapters/`,
register it in `stages/scraper/source_client.py`. No other files need to change.

**Changing the prompt:** add a new versioned file in
`stages/extract/prompts/`, then set `PROMPT_VERSION` in the environment. Never
edit existing version files — they are the historical record, and
`prompt_version` is stored on every `AIResponse` so evolutions stay comparable.

**Changing the model:** don't, mid-evolution. `model_version` is stored on every
`AIResponse`. Swapping models between evolutions makes the deltas
uninterpretable — if you must switch, treat everything before the switch as a
separate baseline.

**Changing lexicon files:** edit the JSON directly. Run
`scripts/validate_lexicon.py` after every change.

---

## Testing

```
unit/          Isolated. Everything external is mocked. Fast. Always run.
integration/   Components wired together. mongomock, no network. Always run.
live/          Real external APIs. Costs quota, needs secrets. Opt-in only.
e2e/           Full request flows through the API (api/tests/ only).
```

Live tests are gated by the `live` pytest marker and skipped unless an API key
is present. `pyproject.toml` excludes them by default:

```toml
[tool.pytest.ini_options]
addopts = "--import-mode=importlib -m 'not live'"
markers = ["live: hits a real external API, costs quota"]
```

Run them deliberately:
```
pytest backend/pipeline/tests/live/ -m live -v -s
```

Never wire live tests into CI. They are non-deterministic, cost money, and
require a secret.

---

## Frontend

Two separate Next.js apps. They share components from `frontend/ui/` and types
from `frontend/types/`.

```
frontend/
  public-dashboard/            Public-facing sentiment dashboard (no auth)
    src/app/                   Next.js pages
    src/features/              Feature folders mirroring the API domains
      dashboard/               Market gauge, ticker list, event list
      ticker/                  Ticker detail page, dual-axis chart
      search/                  Ticker search
    src/lib/                   API client, formatters, query keys
  admin-panel/                 Authenticated admin audit panel
    src/app/                   Next.js pages (login, audit)
    src/features/
      audit/                   Audit table, correction form
      auth/                    Login form, auth hook
    src/lib/                   API client, query keys
  ui/                          Shared React components used by both apps
    src/
      SentimentGauge.tsx       Gauge component
      SentimentBadge.tsx       Score badge
      Sidebar.tsx              Navigation sidebar
      Breadcrumb.tsx           Breadcrumb navigation
      Disclaimer.tsx           Sentiment disclaimer footer
  types/                       TypeScript types generated from OpenAPI spec
    generated/api.types.ts     Auto-generated — do not edit manually
    enums.ts                   Frontend enums
    generate.sh                Run this to regenerate types after OpenAPI changes
```

**Regenerating types after API contract changes:** run
`frontend/types/generate.sh`. Never edit `generated/api.types.ts` by hand.

---

## Evaluation

```
evaluation/
  cluster_threshold.py Clustering threshold sweep — see docs/CLUSTERING_THRESHOLD.md
  runner.py            Runs extraction against the evaluation set
  metrics.py           Computes bucket agreement rate against ground truth
  results/             JSON results per evolution — append only, never overwrite
                       (removed 2026-08-23; recreate with that rule intact)
```

**Hard rules:**
- `results/` files are append-only. Add a new file for each new evaluation run —
  never overwrite existing ones. The directory does not currently exist; the rule
  applies from the moment it is recreated.
- Evaluation uses bucket agreement, not raw float matching. Buckets are derived
  at read time from the stored float — never persisted alongside it.

---

## Docs

```
docs/
  ARCHITECTURE.md               System design, container diagram, data flow
  CLUSTERING_THRESHOLD.md       Threshold selection method and results
  FOLDER_STRUCTURE_GUIDANCE.md  This file
  ONBOARDING.md                 Setup instructions for new members
  mongodb_schema.md             All collections with field definitions and indexes
  openapi.yaml                  REST API contract — source of truth for all endpoints
  adr/                          Architecture Decision Records
    ADR-001                     Why score math lives in core/formulas.py
    ADR-002                     Why JWT over session store
    ADR-003                     Why codegen over manual types
    ADR-004                     Workspace structure decisions
```

If you make an architectural decision that affects the whole team, write an ADR.
Copy the format of an existing one.

---

## Scripts

One-off ops scripts. Run manually, not by CI.

```
scripts/
  init_db.py           Creates MongoDB collections, indexes, and seed data — run once on setup
  reset_dev_db.py      Drops and recreates the dev database — never point this at production
  seed_admins.py       Creates admin user accounts — reads credentials from env vars
  validate_lexicon.py  Validates lexicon JSON files for schema correctness — run after any lexicon edit
  run_evaluation.py    Triggers an evaluation run
```

---

## CI/CD

```
.github/workflows/
  ci.yml                  Orchestrator — triggers all checks on PR
  ci-api.yml              Lints and tests backend/api/
  ci-pipeline.yml         Lints and tests backend/pipeline/
  ci-frontend.yml         Lints and type-checks frontend/
  codegen-types.yml       Regenerates frontend/types/ when openapi.yaml changes
  schedule-pipeline.yml   Cron trigger for the pipeline
  schedule-eod.yml        Cron trigger for EOD batch aggregation
```

This block is the intended shape. Most of these files are still 0 bytes — `STATE.md` lists which
ones actually have content. Scheduled workflows run **only from the default branch**, so a cron
added on a feature branch does nothing until it merges.

All checks run on every PR to `main`. You cannot merge without passing CI. Do
not bypass unless you are the project lead and the commit is structural/chore
only.

**Never use the GitHub web UI "Add files via upload".** It creates commits
outside branch pointers and breaks the history. Push from git.

---

## Quick reference — where does my code go?

| Task | Location |
|---|---|
| Add a new API endpoint | `backend/api/features/<new_feature>/` |
| Add a new news source | `backend/pipeline/stages/scraper/adapters/` + register in `scraper/source_client.py` |
| Change the LLM prompt | `backend/pipeline/stages/extract/prompts/` — new versioned file only |
| Change the LLM request schema | `backend/pipeline/stages/extract/client.py` |
| Change what gets stored per extraction | `backend/core/schemas/sentiment.py` |
| Change scoring formula | `backend/core/formulas.py` — coordinate with both teams |
| Add a shared Python enum | `backend/core/enums.py` |
| Add a shared React component | `frontend/ui/src/` |
| Add a frontend page | `frontend/public-dashboard/src/app/` or `frontend/admin-panel/src/app/` |
| Update lexicon data | `backend/pipeline/lexicon/` — run `validate_lexicon.py` after |
| Update DB schema | `docs/mongodb_schema.md` first, then `scripts/init_db.py` |
| Record an architectural decision | `docs/adr/ADR-00N-title.md` |
| Write a one-off ops script | `scripts/` |