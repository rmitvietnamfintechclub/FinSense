# STATE.md

Current status of the repo. **Everything here is verified against the tree, not inferred from
docs** — a lot of this project is deliberately-seeded empty scaffolding, so a path existing is not
evidence a feature exists.

Architecture lives in `CLAUDE.md`, the pipeline's internals in `docs/PIPELINE.md`. This file only
tracks *what works right now*.

**Last verified: 2026-08-23.** Re-verify before trusting anything below if the date is stale:

```shell
uv run --extra dev python -m pytest -q                  # suite health
ruff check backend/                                     # the only check CI runs
find . -path ./.venv -prune -o -name '*.py' -size -1c -print   # find the empty placeholders
```

## Component status

| Component | Status |
|---|---|
| Pipeline `rss → cluster → scraper → extract → aggregate` | **Verified end to end on live data** |
| EOD batch (`stages/eod_batch/`) + VNDirect price adapter | Implemented; never run against real data |
| API — ticker + dashboard features | Implemented, **not runnable** (see below) |
| API — auth, audit, events, history, internal | Empty files, routers commented out in `main.py` |
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

- **Test suite: 41 failing, 196 passing, 10 skipped.** The failures split into three unrelated
  causes, and only one is a stale expectation:
  - **24 in `test_eod_batch.py` — environment, not code.** `BulkOperationBuilder.add_update() got an
    unexpected keyword argument 'sort'`. pymongo 4.17's `UpdateOne` always passes `sort`; mongomock
    4.3.0 does not accept it, and **4.3.0 is the newest release**, so no upgrade fixes this. Any
    `bulk_write([UpdateOne(...)])` is untestable under mongomock. mongomock also doesn't implement
    `array_filters` at all, which the scraper and extract stages both use.
  - **15 in `test_dashboard.py` — stale expectation.** They monkeypatch
    `dashboard.service.get_database`, which the module no longer has.
  - **2 others**: one `NoneType` subscript in `test_eod_batch.py`, one logging assertion in
    `test_price_adapter.py`.
- **`ruff check backend/` reports 3 errors** — 2× `BLE001` (blind `except Exception`), 1× `DTZ001`
  (naive datetime in a test). CI only runs ruff, so this is the gate that matters and it is red.
- No test execution in CI at all; `ci.yml` runs ruff and nothing else.

## Known broken / blocked

- **The API cannot run.** `fastapi` and `uvicorn` are imported by `backend/api` but absent from
  `pyproject.toml` and `uv.lock`. A clean `uv sync` cannot serve the API.
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
- **`schedule-eod.yml` invokes a module path that doesn't exist** —
  `backend.pipeline.stages.aggregate.eod_batch`, but the module lives at
  `backend.pipeline.stages.eod_batch.eod_batch`. That workflow fails on every run.
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

## Empty scaffolding inventory

Seeded ahead of implementation, all 0 bytes:

- All four `docs/adr/ADR-00*.md`.
- 5 of 7 workflows — `ci-api.yml`, `ci-frontend.yml`, `ci-pipeline.yml`, `codegen-types.yml`,
  `schedule-pipeline.yml` — plus `.github/dependabot.yml` and `.github/CODEOWNERS`. Only `ci.yml`
  and `schedule-eod.yml` have content.
- Every `frontend/**/*.tsx`, every frontend `package.json`/`tsconfig.json`/`next.config.ts`,
  `frontend/types/generate.sh`, `frontend/types/generated/api.types.ts`.
- `evaluation/runner.py`, `evaluation/metrics.py`. (`evaluation/README.md` and the whole
  `evaluation/results/` directory were deleted on 2026-08-23; only `cluster_threshold.py` remains
  functional.)
- `scripts/seed_admins.py`, `scripts/run_evaluation.py`.
- `backend/core/exception.py` — no shared exception hierarchy; error handling is ad hoc per module.
- `backend/api/tests/conftest.py` — `backend.*` imports resolve only because `uv sync` installs the
  project editable into `.venv`. Run API tests through `uv run`.
- Prompts `v2.txt` and `v3.txt`. `PROMPT_VERSION` defaults to `v1`, the only one with content.

## Documentation drift

Trust the tree over the docs.

- `docs/mongodb_schema.md` documents a `concept_dictionary` collection that `scripts/init_db.py`
  never creates, and a `needs_review` field on `aggregated_analysis` that no Pydantic schema has.
- `README.md` links to `backend/README.md` and `frontend/README.md`, neither of which exists.

## Next up

Ordered by what unblocks the most:

1. Throttle the scraper — you lose real articles every run and it worsens with each one.
2. Resolve which Gemini limit you're hitting, from the quota dashboard. That decides whether the
   answer is retries/backoff or a paid tier.
3. Add `fastapi`/`uvicorn` to `pyproject.toml` — nothing about the API can be verified until then.
4. Fix the 3 ruff errors; CI is red.
5. Close the resume gap in `run_pipeline` so a stopped run can be continued without a reset.
6. Fix `schedule-eod.yml`'s module path.
7. Repair the remaining test failures, then add a test job to CI so they can't rot again.
8. Populate the ADRs — the decisions are named but never justified in-repo.
