# STATE.md

Current status of the repo. **Everything here is verified against the tree, not inferred from
docs** — a lot of this project is deliberately-seeded empty scaffolding, so a path existing is not
evidence a feature exists.

Architecture lives in `CLAUDE.md`, the pipeline's internals in `docs/PIPELINE.md`. This file only
tracks *what works right now*.

**Last verified: 2026-08-30.** Re-verify before trusting anything below if the date is stale:

```shell
uv run --extra dev python -m pytest -q                  # suite health
ruff check backend/                                     # the only check CI runs
find . -path ./.venv -prune -o -name '*.py' -size -1c -print   # find the empty placeholders
```

## Component status

| Component | Status |
|---|---|
| Pipeline `rss → cluster → scraper → extract → aggregate` | **Verified end to end on live data.** Resumable since 2026-08-29 — `run_pipeline` gates on outstanding work, not on new articles. Fetches paced since 2026-08-30 |
| EOD batch (`pipeline/eod_batch/`) + VNDirect price adapter | Reviewed and hardened 2026-08-25; suite green, **never run against real data** |
| API — ticker + dashboard features | Implemented and runnable; **smoke-tested against live Atlas data 2026-08-28** |
| API — auth | **Implemented.** `POST /api/auth/login` (JWT, bcrypt) + `audit/guard.py::require_admin`. The app refuses to boot without `JWT_SECRET_KEY` (2026-08-30). **No admin seeded yet** — run `scripts/seed_admins.py` before first login |
| API — audit | **Implemented.** `/audit/summary`, `/audit/articles`, `PATCH /audit/events/{cluster_id}/{source}`, `/audit/log`. Read paths verified against live Atlas data; the PATCH write path is covered by unit tests only |
| Docs | `README.md`, `backend/README.md`, `PIPELINE.md`, `FOLDER_STRUCTURE_GUIDANCE.md`, `mongodb_schema.md`, `CLAUDE.md` swept 2026-08-30. `frontend/README.md` and `docs/ARCHITECTURE.md` still missing |
| API — contract parity | **14 documented endpoints, 14 implemented, zero drift** against `docs/openapi.yaml` |
| Frontend (both apps, `ui/`, `types/`) | Every file 0 bytes — cannot be installed or run |
| Evaluation harness | Only `cluster_threshold.py` works; runner/metrics empty, no ground truth |

## Verified pipeline run

A full run over a live 109-article feed snapshot (2026-08-23), after the round-trip work below:

| Stage | Time | Notes |
|---|---|---|
| RSS | 1.5s | 110 fetched → 109 kept |
| CLUSTER | 22.5s | 78 clusters (68 singletons, 10 multi); ~10.7s of this is embedding |
| SCRAPE | 9.8s | 68/81 bodies — 13 lost to VnExpress HTTP 429 |
| EXTRACT | 0.5s | stopped on the first 429, as designed |
| AGGREGATE | 3.7s | |
| **Total** | **38.3s** | down from 571.3s before the round-trip work |

Current dev database (`FinSense_dev`): 109 articles, 78 event_clusters, 30 daily_sentiment_history.
**Those 78 clusters have zero extractions and cannot currently be completed** — see the resume gap
below.

## Health

- **Test suite: 415 passing, 0 failing, 10 skipped — green as of 2026-08-30**, for the first time
  in this repo's history. `test_dashboard.py` was rewritten that day: the old file predated the
  sync->async migration, monkeypatched a `service.get_database` that no longer exists, and all 15
  of its tests failed. All four dashboard endpoints now have coverage (23 tests).
- `test_dashboard.py` and `test_main.py` drive async services with `asyncio.run()` from sync test
  functions — there is no pytest-asyncio and none is needed. `test_dashboard.py` puts a small async
  facade over mongomock rather than a hand-written fake, so `get_tickers`' real aggregation pipeline
  is executed instead of re-asserted; its client is built `tz_aware=True` to match
  `database_async.py`, without which mongomock returns naive datetimes and `age_in_hours` raises.
- `test_main.py` was 0 bytes until 2026-08-29 and now holds 14 tests — the orchestrator's first
  coverage. The query-semantics half runs against mongomock: the resume path only reads
  (`find`/`$elemMatch`/`$size`/`$exists`), so none of the `bulk_write`/`array_filters` gaps apply.
- **`ruff check backend/` is clean.** CI only runs ruff, so this is the gate that matters.
- `test_eod_batch.py` and `test_price_adapter.py` are fully green (57 tests). The former no longer
  uses mongomock for `daily_sentiment_history` — see `FakeHistoryCollection`.
- `test_jwt_handler.py` (19), `test_guard.py` (13) and `test_audit.py` (36) are green — auth and
  the audit panel are the best-covered API areas. The audit PATCH write path is fake-collection
  only; `array_filters` cannot run under mongomock (see CLAUDE.md).
- No test execution in CI at all; `ci.yml` runs ruff and nothing else.

## Known broken / blocked

- **The API has never touched a real database.** Endpoints were verified with a hand-written fake
  collection only. Nothing has confirmed the `event_clusters` documents the pipeline actually writes
  round-trip through the dashboard queries.
- **Live-vs-historical weighting disagree by design.** Serving queries window and decay on
  `updated_at`, while the EOD batch keys the day on `created_at` (documented in CLAUDE.md). The
  cluster stage bumps `updated_at` on every rewrite, so an old event that gains one article is
  weighted as brand new in the live gauge but stays on its original day in the chart. Accepted
  deliberately on 2026-08-28; revisit if the two views visibly contradict each other.
- **VnExpress rate-limits the scraper.** 78 sequential requests with no delay or backoff earned 3
  HTTP 429s on one run and 13 on the next, and it escalates with repeated runs. Paced on
  2026-08-30: `run_scraper` now waits `SCRAPER_DELAY_SECONDS` plus up to `SCRAPER_JITTER_SECONDS`
  between fetches (1.0s + 0..0.5s), never before the first and never for a source it skips. Costs a
  78-fetch run roughly 80-120s. **Still open:** there is no backoff on a 429 specifically, and no
  failure marker — a body that can never be fetched is retried on every run until it ages out of
  `CLUSTER_LOOKBACK_DAYS`, since "fetch failed" and "not fetched yet" are the same state in the
  document. Pacing bounds the rate, not the total.
- **The Gemini key hits a rate limit almost immediately.** One run got 19 extractions before 429s;
  the next got 0. Which limit (RPM / RPD / TPM) is unresolved — the 429 body is generic. Check the
  quota page at ai.google.dev before writing retry logic. `LLM_MAX_RETRIES` is `1`.
  Measured 2026-08-29: a `v3` prompt is ~58,000 chars (~16,600 tokens), of which ~55,000 is
  fixed reference payload — `SENTIMENT_v3.md` + `AI_CONFIDENCE_v3.md` + the lexicon — resent
  on every article. Roughly triple `v2`. Relevant only if the binding limit turns out to be
  TPM; deliberately not acted on (2026-08-29).
- **Neither cron is live.** `schedule-pipeline.yml` (hourly, written 2026-08-29) and
  `schedule-eod.yml` both have content only on the working branch; on `main` both files are still
  0 bytes. Scheduled workflows run **only from the default branch**, so nothing is scheduled until
  that merges. Merge order matters: the EOD rollup writes 30 null rows for every day the pipeline
  did not run, so the pipeline cron must be live first.
- **No repository secrets exist.** `repos/.../actions/secrets` returns `total_count: 0`
  (re-verified 2026-08-29), so `MONGODB_URI` and `LLM_API_KEY` are unset in Actions and both jobs
  would die at `get_client()` / `_get_model()`. Atlas's IP access list also has to admit GitHub
  runners (they have no fixed IPs) before a run can connect.
- **Resume re-attempts failed fetches every run.** `run_pipeline` gates on work rather than on new
  articles (2026-08-29), and `load_unfinished_clusters` feeds the backlog back into
  scrape/extract/aggregate — never through `run_cluster`, so `updated_at` does not move. Because
  the scraper records no failure marker, a body it cannot fetch stays "unfinished" and is
  re-attempted on **every** run until it ages out of `CLUSTER_LOOKBACK_DAYS` — up to ~72 times on
  an hourly cron. Pacing (above) spaces those attempts out; only a per-source attempt counter would
  stop them, and that persists a new field on `source_breakdown`.
- **`uv sync` installs the CUDA torch stack.** `torch==2.13.0` pulls 43 `nvidia-*` packages, several
  GB, on every cold cache. On an hourly cron that makes `schedule-pipeline.yml`'s 20-minute timeout
  tighter than its "38s verified run" comment suggests, and the multi-GB uv cache entry can
  LRU-evict the statically-keyed 1 GB Hugging Face entry from the repo's 10 GB Actions budget —
  reinstating the model re-download the cache step exists to prevent. A CPU-only torch index would
  fix both; it is a lockfile change, so it has not been made.
- **The two crons can overlap.** `schedule-pipeline.yml` (17:00 UTC among others) and
  `schedule-eod.yml` (17:30 UTC) use different concurrency groups, so an hourly run can still be
  writing `ai_response`s to clusters created before 17:00 UTC — yesterday in ICT — while the EOD
  batch rolls that same ICT day up. The history row then misses a late extraction.
- **Bare `pytest` does not exclude `live` tests.** No `[tool.pytest.ini_options]` block, so the
  `live` marker is unregistered and quota-costing Gemini tests are only kept out by their `skipif`
  on a missing `LLM_API_KEY`.
- **`ci.yml` lints on Python 3.11** while `pyproject.toml` requires `>=3.13`. It passes only because
  ruff doesn't execute the code.
- **Dead lexicon data.** `pipeline/lexicon/concept_dictionary.json` is referenced by no Python
  code. `relevance_keywords.json` is loaded by `stages/rss/filter.py`, and
  `vietnam_financial_lexicon.json` by `stages/extract/prompt_builder.py` since prompt `v2`.
- **`test.py` at the repo root** is a scratch script that hits live RSS feeds on import.

## Open quality questions

Not bugs — unresolved calibration, flagged by the live runs.

- **The clustering threshold was calibrated on the wrong text.** `CLUSTERING_THRESHOLD.md` tuned
  0.91 against *headlines only*; production embeds title + summary, which shifts similarities up
  ~0.01 and makes ~40% more pairs merge-eligible. Re-run the sweep on title+summary.
- **The threshold sits on a cliff.** Real-data pairwise similarity is very tight (p50 0.81, p99
  0.90, max 0.96), so 0.91 is above the 99th percentile. 0.88 collapses 109 articles into 36
  clusters with a 56-article blob; 0.86 gives 4. Do not lower it casually.
- **Topic chaining over-merges.** One run produced a 12-article "VN-Index" cluster and a 10-article
  "gold price" cluster, each spanning several distinct events.
- **Extraction quality is unrefined** (prompt work deferred): articles listing many tickers get
  ~0.5 assigned to all of them; unrelated tickers come back as exactly `0.0`, which renders as
  genuine neutral; and an article about an out-of-vocabulary company (PNJ) had its sentiment
  attributed to unrelated tickers rather than returning an empty list.
- **`EXTRACTION_TEMPERATURE` is ignored** by `gemini-3.6-flash`, which uses fixed sampling defaults.
  Extractions are not deterministic, which weakens prompt-evolution comparisons.

## Audit panel — known v1 limitations

- **No removal mechanism for a hallucinated ticker.** `error_type: "Wrong ticker"` is recorded for
  the US-G5 taxonomy, but the bad score stays in `source_breakdown` and therefore in
  `aggregated_analysis`. Deliberate product decision for v1; revisit alongside the extraction-quality
  work, since STATE already records tickers being attributed to unrelated companies.
- **`pending_review` never reaches zero.** It is `total_articles - audited_articles` by product
  decision, so it counts non-centroid articles that have no `ai_response` and can never be audited.
- **`PATCH /audit/events/...` is not transactional.** It updates `event_clusters` then inserts into
  `audit_log` as two writes, so a failed insert leaves a source audited with no log entry. Low
  severity because the update is idempotent — the admin sees a 500 and a retry heals the state.
  Fix with a Motor session if audit history ever becomes compliance-relevant.
- **No rate limiting on `POST /auth/login`.** bcrypt's cost slows brute force but does not stop it.
- **`representative_article.title` is null on clusters written before 2026-08-28.** No backfill
  exists by choice — the dev database is disposable, so re-ingesting populates titles naturally.
  The API falls back to `event_title` for any row that stays null.

## Empty scaffolding inventory

Seeded ahead of implementation, all 0 bytes:

- `docs/adr/ADR-001`, `ADR-003`, `ADR-004`. (`ADR-002` is now written.)
- `.github/dependabot.yml` and `.github/CODEOWNERS`. The four empty workflow placeholders
  (`ci-api.yml`, `ci-frontend.yml`, `ci-pipeline.yml`, `codegen-types.yml`) were deleted on
  2026-08-29 — an empty file in `.github/workflows/` shows up as an invalid workflow in the Actions
  tab. All three remaining workflows have content. `docs/FOLDER_STRUCTURE_GUIDANCE.md` still lists
  the deleted four as intended; recreate them from there if the split CI is wanted.
- Every `frontend/**/*.tsx`, every frontend `package.json`/`tsconfig.json`/`next.config.ts`,
  `frontend/types/generate.sh`, `frontend/types/generated/api.types.ts`.
- `evaluation/runner.py`, `evaluation/metrics.py`. (`evaluation/README.md` and the whole
  `evaluation/results/` directory were deleted on 2026-08-23; only `cluster_threshold.py` remains
  functional.)
- `scripts/run_evaluation.py`. (`scripts/seed_admins.py` is now implemented.)
- `backend/core/exception.py` — no shared exception hierarchy; error handling is ad hoc per module.
- `backend/api/tests/conftest.py`, `tests/integration/test_api_routes.py`,
  `tests/e2e/test_admin_login_flow.py` — still 0 bytes. `backend.*` imports resolve only because
  `uv sync` installs the project editable into `.venv`. Run API tests through `uv run`.

## Documentation drift

Trust the tree over the docs.

**Docs were swept on 2026-08-30** — `README.md`, `backend/README.md`, `docs/PIPELINE.md`,
`docs/FOLDER_STRUCTURE_GUIDANCE.md`, `docs/mongodb_schema.md` and `CLAUDE.md` all reflect the tree
as of that date. What is still knowingly out of step:

- `docs/mongodb_schema.md`'s `concept_dictionary` collection and `aggregated_analysis.needs_review`
  field are **documented but not implemented** — nothing creates or writes either. Both are now
  labelled `NOT IMPLEMENTED` in place rather than deleted, so the intent survives; build them or
  delete those sections before anyone codes against them. (Its `articles` block was corrected
  2026-08-28 — it had listed `article_id`/`ingested_at`, which no code writes, and omitted
  `title`/`summary`/`full_content`. `admin_users` was added the same day.)
- `README.md` links to `frontend/README.md` and `docs/ARCHITECTURE.md`; neither exists. Both are
  flagged as TODO at the link site.
- `docs/FOLDER_STRUCTURE_GUIDANCE.md` still describes the frontend and evaluation trees as intended
  shapes. Both are almost entirely 0-byte scaffolding — see the inventory above.
- `docs/RUBRICS/SENTIMENT.md` and `AI_CONFIDENCE.md` are the unversioned originals. The files the
  prompt actually loads are the versioned copies under
  `backend/pipeline/stages/extract/prompts/docs/`, pinned by filename to `PROMPT_VERSION`. Editing
  the `docs/RUBRICS/` copies changes nothing at runtime.

## Next up

Ordered by what unblocks the most:

1. Resolve which Gemini limit you're hitting, from the quota dashboard. That decides whether the
   answer is retries/backoff or a paid tier.
2. Seed an admin (`scripts/init_db.py` then `scripts/seed_admins.py`) and exercise the audit
   `PATCH` end to end — it is the one write path never run against real Mongo.
3. Build `frontend/admin-panel` (login + audit queue). Regenerate
   `frontend/types/generated/api.types.ts` first — `docs/openapi.yaml` changed substantially on
   2026-08-28 and again on 2026-08-30 (`CorrectedScore`), so the generated types are stale.
4. Add a test job to CI — the suite is green, and only ruff gates a merge.
5. Batch the EOD price fetch — 30 sequential requests per night where VNDirect's `q` accepts a
   comma-separated code list. Also worth a projection on the day's `find()` and a single pass in
   `_collect_ticker_scores` instead of one per ticker.
6. Populate the ADRs — the decisions are named but never justified in-repo.
