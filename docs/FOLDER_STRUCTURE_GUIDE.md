# Codebase Guide — FIN-SENSE 2.0

This document tells you where your code belongs based on what you're working on.
Read this before touching anything in the repo.

---

## Top-level map

```
backend/       Python backend — pipeline and API
frontend/      Next.js frontend — public dashboard and admin panel
evaluation/    Frozen test set and evaluation harness — read-only test data
docs/          Architecture, schema, onboarding, ADRs, OpenAPI spec
scripts/       One-off ops scripts (DB init, seeding, validation)
.github/       CI/CD workflows and branch protection rules
```

---

## Backend

### `backend/core/` — shared layer

Imported by both the API and the pipeline
```
config.py      Environment variable loading and validation
database.py    MongoDB connection — single shared client
enums.py       Shared Python enums used across api and pipeline
exception.py   Base exception classes
formulas.py    Apply mathematical formulas
logging.py     Shared log formatter and configuration
```

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
  e2e/                         End-to-end flows (login, frozen set guard)
```

**Adding a new API endpoint:** create a new folder under `features/` with `router.py`, `schemas.py`, `service.py`. Register the router in `main.py`.

### `backend/pipeline/` — scheduled pipeline 

Runs on a 30-minute cron via GitHub Actions. Writes to MongoDB. Never calls the API.

```
main.py                        Pipeline entrypoint, stage orchestration
stages/                        Processing stages in execution order
  ingest/                      RSS fetch, dedup filter, source tagging
  clean/                       HTML stripping, text normalization, relevance filter
  cluster/                     Sentence embedding, HDBSCAN clustering, centroid selection
  extract/                     LLM extraction via Gemini
    llm/
      adapters/gemini.py       Gemini adapter — swap here to change LLM provider
      prompts/                 Versioned prompt files (v1.txt, v2.txt, v3.txt)
      client.py                LLM client wrapper
    prompt_builder.py          Loads active prompt version from config
    output_schema.py           Pydantic schema for LLM response
    response_parser.py         Parses and validates LLM output
    unmapped_handler.py        Logs unknown concepts for admin review
  aggregate/                   EOD batch scoring, event aggregation
external/
  news_sources/
    adapters/                  One file per news source (cafef.py, vnexpress.py)
    source_client.py           Source-agnostic client, delegates to adapters
lexicon/                       JSON config files — read by pipeline at runtime
  vietnam_financial_lexicon.json   Sentiment terms, abbreviations, aliases
  concept_list.json                Known concept taxonomy
  ticker_coverage_list.json        Tickers the system tracks
  relevance_keywords.json          Keywords used by relevance filter
tests/
  unit/                        Unit tests per stage
  integration/                 Full pipeline integration test
```

**Adding a new news source:** add an adapter in `external/news_sources/adapters/`, register it in `source_client.py`. No other files need to change.

**Changing the prompt:** add a new versioned file in `stages/extract/llm/prompts/`, update the active version in config. Do not edit existing version files — they are the historical record.

**Changing lexicon files:** edit the JSON directly. Run `scripts/validate_lexicon.py` after every change.

---

## Frontend 

Two separate Next.js apps. They share components from `frontend/ui/` and types from `frontend/types/`.

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
      audit/                   Audit table, correction form, unmapped panel
      auth/                    Login form, auth hook
    src/lib/                   API client, query keys
  ui/                          Shared React components
    src/
      SentimentGauge.tsx       Gauge component — used in both apps
      SentimentBadge.tsx       Score badge
      Sidebar.tsx              Navigation sidebar
      Breadcrumb.tsx           Breadcrumb navigation
      Disclaimer.tsx           Sentiment disclaimer footer
  types/                       TypeScript types generated from OpenAPI spec
    generated/api.types.ts     Auto-generated — do not edit manually
    enums.ts                   Frontend enums
    generate.sh                Run this to regenerate types after OpenAPI changes
```

**Regenerating types after API contract changes:** run `frontend/types/generate.sh`. Never edit `generated/api.types.ts` by hand.

---

## Evaluation

```
evaluation/
  frozen_test_set/     Hand-labeled benchmark — NEVER modify, NEVER write to this
  runner.py            Runs extraction against the frozen test set
  metrics.py           Computes precision/recall/F1
  results/             JSON results per evolution — append only, never overwrite
    evolution_1_baseline.json
    evolution_2_domain.json
    evolution_3_prompting.json
  requirements.txt     Separate install — run independently from backend
```

**Hard rules:**
- `frozen_test_set/` is read-only forever. No exceptions.
- `results/` files are append-only. Add a new file for each new evaluation run — do not overwrite existing ones.
- Run `scripts/run_evaluation.py` to execute an eval. Never run the runner directly against production data.

---

## Docs

```
docs/
  ARCHITECTURE.md               System design, container diagram, data flow
  MONGODB_SCHEMA.md             All 7 collections with field definitions and indexes
  FOLDER_STRUCTURE_GUIDANCE.MD  General guidance to understand repo structure
  ONBOARDING.md                 Setup instructions for new members
  openapi.yaml                  REST API contract — source of truth for all endpoints
  adr/                          Architecture Decision Records
    ADR-001                     Why score_math is an isolated package
    ADR-002                     Why JWT over session store
    ADR-003                     Why codegen over manual types
    ADR-004                     Workspace structure decisions
```

If you make an architectural decision that affects the whole team, write an ADR. Copy the format of an existing one.

---

## Scripts

One-off ops scripts. Run manually, not by CI.

```
scripts/
  init_db.py           Creates MongoDB collections, indexes, and seed data — run once on setup
  seed_admins.py       Creates admin user accounts — reads credentials from env vars
  validate_lexicon.py  Validates lexicon JSON files for schema correctness — run after any lexicon edit
  run_evaluation.py    Triggers an evaluation run against the frozen test set
```

---

## CI/CD

```
.github/workflows/
  ci.yml               Orchestrator — triggers all checks on PR
  ci-api.yml           Lints and tests backend/api/
  ci-pipeline.yml      Lints and tests backend/pipeline/
  ci-frontend.yml      Lints and type-checks frontend/
  codegen-types.yml    Regenerates frontend/types/ when openapi.yaml changes
  schedule-pipeline.yml   Cron trigger for the pipeline (every 30 min)
  schedule-eod.yml        Cron trigger for EOD batch aggregation
```

All checks run on every PR to `main`. You cannot merge without passing CI. Do not bypass unless you are the project lead and the commit is structural/chore only.

---

## Quick reference — where does my code go?

| Task | Location |
|---|---|
| Add a new API endpoint | `backend/api/features/<new_feature>/` |
| Add a new news source | `backend/pipeline/external/news_sources/adapters/` |
| Change the LLM prompt | `backend/pipeline/stages/extract/llm/prompts/` — new versioned file |
| Change scoring formula | `backend/core/` — coordinate with both teams |
| Add a shared Python enum | `backend/core/enums.py` |
| Add a shared React component | `frontend/ui/src/` |
| Add a frontend page | `frontend/public-dashboard/src/app/` or `frontend/admin-panel/src/app/` |
| Update lexicon data | `backend/pipeline/lexicon/` — run validate_lexicon.py after |
| Update DB schema | `docs/MONGODB_SCHEMA.md` first, then `scripts/init_db.py` |
| Record an architectural decision | `docs/adr/ADR-00N-title.md` |
| Write a one-off ops script | `scripts/` |
