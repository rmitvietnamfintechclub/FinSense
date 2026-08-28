# STATE.md

Current status of the repo. **Everything here is verified against the tree, not inferred from
docs** — a lot of this project is deliberately-seeded empty scaffolding, so a path existing is not
evidence a feature exists.

Architecture lives in `CLAUDE.md`, the pipeline's internals in `docs/PIPELINE.md`. This file only
tracks *what works right now*.

**Last verified: 2026-08-25.** Re-verify before trusting anything below if the date is stale:

```shell
uv run --extra dev python -m pytest -q                  # suite health
ruff check backend/                                     # the only check CI runs
find . -path ./.venv -prune -o -name '*.py' -size -1c -print   # find the empty placeholders
```

## Component status

| Component | Status |
|---|---|
| Pipeline `rss → cluster → scraper → extract → aggregate` | **Verified end to end on live data** |
| EOD batch (`pipeline/eod_batch/`) + VNDirect price adapter | Reviewed and hardened 2026-08-25; suite green, **never run against real data** |
| API — ticker + dashboard features | Implemented and runnable; **smoke-tested against live Atlas data 2026-08-28** |
| API — auth | **Implemented.** `POST /api/auth/login` (JWT, bcrypt) + `audit/guard.py::require_admin`. No admin seeded yet — run `scripts/seed_admins.py` before first login |
| API — audit | **Implemented.** `/audit/summary`, `/audit/articles`, `PATCH /audit/events/{cluster_id}/{source}`, `/audit/log`. Read paths verified against live Atlas data; the PATCH write path is covered by unit tests only |
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

- **Test suite: 15 failing, 361 passing, 10 skipped.** One cause, all in `test_dashboard.py`:
  they monkeypatch `dashboard.service.get_database` and call the services synchronously. The module
  is async + injected-`db` and has moved further since (pagination, `rank`, `sources` counts), so
  the whole file needs rewriting, not patching. All four dashboard endpoints are untested.
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
- **A stopped run cannot be resumed.** `run_pipeline` returns early when RSS finds no new articles,
  but RSS has already persisted the batch. If extraction dies partway, the next run stops
  immediately and the half-finished clusters are never revisited — despite `run_extract` and
  `run_scraper` both being written to resume. Recovery today is `scripts/reset_dev_db.py`, which
  also discards scraped bodies and forces a re-scrape. **Deliberately left open** (2026-08-23); the
  fix is to feed unfinished clusters back into the stage list rather than gating on new articles.
- **VnExpress rate-limits the scraper.** 78 sequential requests with no delay or backoff earned 3
  HTTP 429s on one run and 13 on the next, and it escalates with repeated runs. There is no
  throttling, jitter, or retry anywhere in `stages/scraper/`.
- **The Gemini key hits a rate limit almost immediately.** One run got 19 extractions before 429s;
  the next got 0. Which limit (RPM / RPD / TPM) is unresolved — the 429 body is generic. Check the
  quota page at ai.google.dev before writing retry logic. `LLM_MAX_RETRIES` is `1`.
- **The EOD cron is not live.** `schedule-eod.yml` has content only on the working branch; on `main`
  the file is still 0 bytes. Scheduled workflows run **only from the default branch**, so nothing is
  scheduled until that merges.
- **No repository secrets exist.** `repos/.../actions/secrets` returns `total_count: 0`, so
  `MONGODB_URI` is unset in Actions and the EOD job would die at `get_client()`. Atlas's IP access
  list also has to admit GitHub runners (they have no fixed IPs) before a run can connect.
- **Nothing populates `event_clusters` on a schedule.** `schedule-pipeline.yml` is 0 bytes. Once the
  EOD cron is live it will roll up whatever a human last ran locally, writing 30 null rows on every
  day nobody ran the pipeline by hand. Schedule the pipeline before trusting the history chart.
- **Bare `pytest` does not exclude `live` tests.** No `[tool.pytest.ini_options]` block, so the
  `live` marker is unregistered and quota-costing Gemini tests are only kept out by their `skipif`
  on a missing `LLM_API_KEY`.
- **`ci.yml` lints on Python 3.11** while `pyproject.toml` requires `>=3.13`. It passes only because
  ruff doesn't execute the code.
- **Dead lexicon data.** `pipeline/lexicon/vietnam_financial_lexicon.json` and
  `concept_dictionary.json` are referenced by no Python code; only `relevance_keywords.json` is
  loaded (by `stages/rss/filter.py`).
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
- 5 of 7 workflows — `ci-api.yml`, `ci-frontend.yml`, `ci-pipeline.yml`, `codegen-types.yml`,
  `schedule-pipeline.yml` — plus `.github/dependabot.yml` and `.github/CODEOWNERS`. Only `ci.yml`
  and `schedule-eod.yml` have content.
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
- Prompts `v2.txt` and `v3.txt`. `PROMPT_VERSION` defaults to `v1`, the only one with content.

## Documentation drift

Trust the tree over the docs.

- `docs/mongodb_schema.md` documents a `concept_dictionary` collection that `scripts/init_db.py`
  never creates, and a `needs_review` field on `aggregated_analysis` that no Pydantic schema has.
  (Its `articles` block was corrected 2026-08-28 — it had listed `article_id`/`ingested_at`, which
  no code writes, and omitted `title`/`summary`/`full_content`. `admin_users` was added the same day.)
- `README.md` links to `backend/README.md` and `frontend/README.md`, neither of which exists.

## Next up

Ordered by what unblocks the most:

1. Throttle the scraper — you lose real articles every run and it worsens with each one.
2. Resolve which Gemini limit you're hitting, from the quota dashboard. That decides whether the
   answer is retries/backoff or a paid tier.
3. Seed an admin (`scripts/init_db.py` then `scripts/seed_admins.py`) and exercise the audit
   `PATCH` end to end — it is the one write path never run against real Mongo.
4. Build `frontend/admin-panel` (login + audit queue). Regenerate
   `frontend/types/generated/api.types.ts` first — `docs/openapi.yaml` changed substantially on
   2026-08-28 and the generated types are stale.
4. Give `schedule-pipeline.yml` content. The EOD rollup is scheduled ahead of the thing it rolls up.
5. Close the resume gap in `run_pipeline` so a stopped run can be continued without a reset.
6. Rewrite `test_dashboard.py` against the async + DI services, then add a test job to CI so it can't rot again.
7. Batch the EOD price fetch — 30 sequential requests per night where VNDirect's `q` accepts a
   comma-separated code list. Also worth a projection on the day's `find()` and a single pass in
   `_collect_ticker_scores` instead of one per ticker.
8. Populate the ADRs — the decisions are named but never justified in-repo.
