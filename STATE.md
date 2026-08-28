# STATE.md

Current status of the repo. **Everything here is verified against the tree, not inferred from
docs** — a lot of this project is deliberately-seeded empty scaffolding, so a path existing is not
evidence a feature exists.

Architecture lives in `CLAUDE.md`, the pipeline's internals in `docs/PIPELINE.md`. This file only
tracks *what works right now*.

**Last verified: 2026-08-28.** Re-verify before trusting anything below if the date is stale:

```shell
uv run --extra dev python -m pytest -q                  # suite health
ruff check backend/                                     # the only check CI runs
find . -path ./.venv -prune -o -name '*.py' -size -1c -print   # find the empty placeholders
```

## Component status

| Component | Status |
|---|---|
| Pipeline `rss → cluster → scraper → extract → aggregate` | **Verified end to end on live data** |
| Extract prompt `v1` | Active (`PROMPT_VERSION` default); no defined sentiment or confidence scale |
| Extract prompts `v2`, `v3` | Written, composed, unit-tested — **never sent to Gemini**; not switched on |
| EOD batch (`pipeline/eod_batch/`) + VNDirect price adapter | Reviewed and hardened 2026-08-25; suite green, **never run against real data** |
| API — ticker + dashboard features | Implemented and runnable; routes smoke-tested, **never run against real Atlas data** |
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

(That run is a 2026-08-23 snapshot, kept because it is the only full end-to-end timing on record.
The database has grown since — the numbers below are current.)

Current dev database (`FinSense_dev`), as of 2026-08-28: **218 articles, 175 event_clusters, 30
daily_sentiment_history, 0 audit_log**, with `created_at` spanning 2026-08-23 → 2026-08-28.

**Extraction coverage is negligible: 6 of 175 clusters carry any `ai_response` at all, and only 3
have a non-empty aggregated ticker list.** The other 169 were clustered and scraped but never
extracted — the Gemini quota stops the stage almost immediately, and the resume gap below means a
later run does not pick them up. 162 clusters do hold real `content_fed_to_ai` bodies, which is
what the `v3` prompt examples were sourced from.

## Health

- **Test suite: 15 failing, 234 passing, 10 skipped** (on `admin/prompt_builder`). One cause, all
  in `test_dashboard.py`:
  they monkeypatch `dashboard.service.get_database` and call the services synchronously. The module
  is async + injected-`db` and has moved further since (pagination, `rank`, `sources` counts), so
  the whole file needs rewriting, not patching. All four dashboard endpoints are untested.
- **`ruff check backend/` is clean.** CI only runs ruff, so this is the gate that matters.
- `test_eod_batch.py` and `test_price_adapter.py` are fully green (57 tests). The former no longer
  uses mongomock for `daily_sentiment_history` — see `FakeHistoryCollection`.
- `test_extract.py` is green (38 tests) and now covers prompt composition: that every placeholder in
  `v2`/`v3` is filled, that `article_text` is substituted last so a scraped body cannot inject a
  reference section, that maintainer notes are stripped, and that `v2` and `v3` load *different*
  rubric files. That last one matters — without it a regression in the strip heuristic would
  silently turn `v3` back into `v2` with no failure.
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
- **Dead lexicon data.** `pipeline/lexicon/concept_dictionary.json` is referenced by no Python
  code. `relevance_keywords.json` is loaded by `stages/rss/filter.py`, and
  `vietnam_financial_lexicon.json` by `stages/extract/prompt_builder.py` — but only when
  `PROMPT_VERSION` is `v2` or later, and it still defaults to `v1`.
- **`test.py` at the repo root** is a scratch script that hits live RSS feeds on import.

## Open quality questions

Not bugs — unresolved calibration, flagged by the live runs.

- **The `v3` example scores are unvalidated judgements.** The article text in every worked example
  is real and cited, but the score attached to each was reasoned from the rubric, not human-labelled.
  Once `v3` is live those numbers become the de-facto specification. The neutral (a) / (c) split —
  measured small lean vs. undeterminable direction — is the distinction carrying the most weight and
  the one most worth a second reader.
- **No way to tell whether `v2`/`v3` actually help.** `EXTRACTION_TEMPERATURE` is ignored by
  `gemini-3.6-flash`, so repeated runs disagree with themselves. A small-sample `v1`-vs-`v3`
  comparison cannot separate a prompt effect from sampling noise, and there is no evaluation harness
  and no frozen test set to do it properly.

- **The clustering threshold was calibrated on the wrong text.** `CLUSTERING_THRESHOLD.md` tuned
  0.91 against *headlines only*; production embeds title + summary, which shifts similarities up
  ~0.01 and makes ~40% more pairs merge-eligible. Re-run the sweep on title+summary.
- **The threshold sits on a cliff.** Real-data pairwise similarity is very tight (p50 0.81, p99
  0.90, max 0.96), so 0.91 is above the 99th percentile. 0.88 collapses 109 articles into 36
  clusters with a 56-article blob; 0.86 gives 4. Do not lower it casually.
- **Topic chaining over-merges.** One run produced a 12-article "VN-Index" cluster and a 10-article
  "gold price" cluster, each spanning several distinct events.
- **Prompts `v2` and `v3` are written but not switched on.** `PROMPT_VERSION` still defaults to
  `v1`, so neither the rubrics, the lexicon, nor `v3`'s worked examples are reaching the model yet.
  Nothing below has been re-measured against either; every symptom in this section was observed
  under `v1`.
- **Fixed preamble cost per article**: `v1` ~200 tokens, `v2` ~10.3k, `v3` ~17k, sent on every
  article. `client.py` requests no explicit prompt caching. Budget for that before switching a
  scheduled run — at ~80 calls on a cold start, `v3` is ~1.4M input tokens per run.
- **`v3`'s `strongly_negative` band has no worked in-vocabulary example.** The corpus it was built
  from (2026-08-23 → 08-28) contains no severe adverse event with a covered ticker as primary
  subject; the slot is filled with a real out-of-vocabulary case (Lộc Trời delisting) that teaches
  the band criteria and the empty-list rule instead. Add a proper one when the corpus has one.
- **Extraction quality is unrefined** (measured under `v1`, whose prompt defines neither scale):
  articles listing many tickers get
  ~0.5 assigned to all of them; unrelated tickers come back as exactly `0.0`, which renders as
  genuine neutral; and an article about an out-of-vocabulary company (PNJ) had its sentiment
  attributed to unrelated tickers rather than returning an empty list. `v2` is the intended fix for
  the first two — it defines both scales and separates "neutral" from "could not tell" — but that is
  a hypothesis until someone runs it.
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
- *(nothing left in this list from the prompts folder — `v2.txt` and `v3.txt` are both
  implemented as of 2026-08-28.)*

## Documentation drift

Trust the tree over the docs.

- `docs/mongodb_schema.md` documents a `concept_dictionary` collection that `scripts/init_db.py`
  never creates, and a `needs_review` field on `aggregated_analysis` that no Pydantic schema has.
- `README.md` links to `backend/README.md` and `frontend/README.md`, neither of which exists.

## Next up

Ordered by what unblocks the most:

1. Throttle the scraper — you lose real articles every run and it worsens with each one.
2. Resolve which Gemini limit you're hitting, from the quota dashboard. That decides whether the
   answer is retries/backoff or a paid tier. This also gates the prompt work: `v3` sends ~17k tokens
   per article, so if the ceiling is TPM rather than RPM, switching to it makes extraction *worse*.
3. Switch `PROMPT_VERSION` to `v3` and run it once against real clusters — it has never reached the
   model. Everything verified so far is string composition.
4. Run the API against a seeded Atlas dev database — every endpoint so far is fake-collection only.
5. Give `schedule-pipeline.yml` content. The EOD rollup is scheduled ahead of the thing it rolls up.
6. Close the resume gap in `run_pipeline` so a stopped run can be continued without a reset.
7. Rewrite `test_dashboard.py` against the async + DI services, then add a test job to CI so it can't rot again.
8. Batch the EOD price fetch — 30 sequential requests per night where VNDirect's `q` accepts a
   comma-separated code list. Also worth a projection on the day's `find()` and a single pass in
   `_collect_ticker_scores` instead of one per ticker.
9. Populate the ADRs — the decisions are named but never justified in-repo.
10. Harvest a real `strongly_negative` example with a *covered* ticker as primary subject, and fill
    the gap in `SENTIMENT_v3.md` (cut a `v4` to do it — the rubric docs are pinned per version).
    Nothing in the 2026-08-23 → 08-28 corpus qualifies.
