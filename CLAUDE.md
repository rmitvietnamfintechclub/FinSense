# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FinSense ingests Vietnamese financial news (CafeF, VnExpress), clusters articles describing the
same market event, and uses Gemini to extract sentiment toward the VN30 tickers and 10 sector
concepts. Scores are confidence-weighted and meant to be human-audited. Monorepo: scheduled
Python pipeline + FastAPI serving API + two Next.js frontends, all over one MongoDB Atlas database.

`docs/FOLDER_STRUCTURE_GUIDANCE.md` is the team's authoritative "where does my code go" doc — read
it before adding files. Note it describes some things that don't match the tree yet (see
[State of the repo](#state-of-the-repo)).

## Commands

```shell
uv sync --extra dev                                  # install (Python >=3.13); dev extra = ruff, pytest, mongomock

uv run python -m backend.pipeline.main               # run the full pipeline once (needs MONGODB_URI, LLM_API_KEY)
uv run python -m backend.pipeline.eod_batch.eod_batch [YYYY-MM-DD]  # EOD batch; date arg re-runs a past day

uv run --extra dev python -m pytest -q               # whole suite
uv run --extra dev python -m pytest backend/pipeline/tests/unit -q         # fast, fully mocked
uv run --extra dev python -m pytest backend/pipeline/tests/unit/test_extract.py::TestX::test_y -v   # single test
uv run --extra dev python -m pytest backend/pipeline/tests/live -m live -v -s   # real Gemini calls, costs quota

ruff check backend/                                  # the only check CI runs

python scripts/init_db.py                            # create collections + indexes (once, per environment)
python scripts/reset_dev_db.py                       # destructive; refuses unless MONGODB_DB_NAME contains dev/test
python scripts/validate_lexicon.py                   # run after any edit to backend/pipeline/lexicon/*.json
uv run python evaluation/cluster_threshold.py        # reproduce the 0.91 clustering threshold sweep
```

There is no `[tool.pytest.ini_options]` block in `pyproject.toml`, so bare `pytest` does **not**
exclude `live` tests and warns about the unregistered `live` marker. Live tests additionally
`skipif` when `LLM_API_KEY` is absent, which is the only thing keeping them out of a plain run.

## Architecture

**Pipeline** (`backend/pipeline/`) — `rss → cluster → scraper → extract → aggregate`, orchestrated
by `run_pipeline()` in `main.py`. **`docs/PIPELINE.md` documents all five stages in detail** — read it
before changing stage internals. Stages hand off through MongoDB, never in memory; that's what
makes the run idempotent and resumable. Clustering deliberately runs *before* scraping — only each
cluster's centroid article gets its body fetched, so `content_fed_to_ai` is `None` until the
scraper stage fills it.

Every stage folder has pure helper modules plus a `stage.py` holding the coordinator
(`run_<stage>`). **The coordinator is the only thing that touches MongoDB**; helpers stay pure and
unit-testable. Collections are injected as a parameter defaulting to `None` and falling back to
`get_database().<collection>` — that's the DI pattern the tests rely on, there's no framework. All
five coordinators follow it; if you add one, keep the `| None = None` default, and **pass a fake
collection explicitly in tests** rather than relying on it — a test that falls through to
`get_database()` writes to the real database.

The EOD batch (`pipeline/eod_batch/`) is a separate cron entrypoint, not part of `run_pipeline`: it
rolls each day's event sentiment into `daily_sentiment_history` and joins the VNDirect closing
price. Day boundaries are ICT (UTC+7) — see `utc_to_ict_date`. An event belongs to the day it was
**created**, never `updated_at`: the cluster stage bumps `updated_at` on every rewrite, so keying on
it would move events between days and stop past-day re-runs from reproducing their original score.

**API** (`backend/api/`) — FastAPI, async via Motor. Reads MongoDB, never calls the LLM, never
imports from `backend.pipeline`. One folder per domain under `features/` with
`router.py` / `schemas.py` / `service.py`, registered in `main.py`. `docs/openapi.yaml` is the
contract source of truth (base path `/api`, bearer JWT on audit endpoints only).

Ticker live scores are computed **at request time** from `event_clusters`
(`features/ticker/aggregator.py`); `daily_sentiment_history` only backs the historical chart.

**Core** (`backend/core/`) — shared by both, must contain nothing specific to one. `formulas.py`
holds all the scoring math (recency decay, time-weighted average, `blend_s_final`,
`confidence_weighted_avg`) as pure functions so pipeline aggregation and API recomputation can't
drift. `SFinalResult.is_empty` distinguishes "no events" from "genuinely neutral 0.0" — both render
differently and must not be collapsed. Sync client (`database.py`, PyMongo) for the pipeline, async
(`database_async.py`, Motor) for the API.

`enums.py` is the frozen vocabulary: 30 VN30 `Ticker`s and 10 `Concept`s. The LLM is constrained to
it; out-of-vocabulary entries in an AI response are logged and dropped, never fatal to the article.

Data files: `core/data/static_ontology.json` (ticker → concept weights, via `core/lexicon.py`) and
`core/data/ticker_metadata.json` (display names + aliases; loading fails loudly if any `Ticker` is
missing an entry). Pipeline-only lexicons live in `backend/pipeline/lexicon/`.

**Frontend** (`frontend/`) — two Next.js apps (`public-dashboard`, `admin-panel`) sharing
`ui/` components and `types/generated/api.types.ts`, which is generated from `docs/openapi.yaml`
by `frontend/types/generate.sh` and must never be hand-edited.

## Rules that bite

- **Prompts are append-only.** Add `stages/extract/prompts/vN.txt` and point `PROMPT_VERSION` at
  it; never edit an existing version file. `prompt_version` and `model_version` are stamped on every
  `AIResponse` so evolutions stay comparable — swapping `LLM_MODEL_NAME` mid-evolution makes the
  deltas uninterpretable, so treat everything before a switch as a separate baseline.
- **Evaluation results are append-only** — one new file per run, never overwrite. The
  `evaluation/results/` directory was removed on 2026-08-23 along with the frozen test set; recreate
  it with that rule intact when the harness is built.
- **Buckets are derived at read time** from the stored float (`core/buckets.py`), never persisted
  alongside it. Evaluation scores bucket agreement, not float equality.
- New scraper source: add an adapter under `stages/scraper/adapters/` and register it in
  `source_client.py` — nothing else changes.
- **`bulk_write` cannot be unit-tested with mongomock.** pymongo 4.17's `UpdateOne` passes a `sort`
  argument mongomock 4.3.0 rejects, and 4.3.0 is the newest release; mongomock also doesn't
  implement `array_filters` at all. Code using either (`scraper`, `extract`, `eod_batch`) needs a
  hand-written fake collection — see `_FakeCollection` in `tests/unit/test_scraper.py`,
  `FakeCollection` in `test_aggregate.py`, or `FakeHistoryCollection` in `test_eod_batch.py`, which
  also enforces a unique index so the upsert contract stays under test. This is why `cluster/stage.py` batches its reads but not
  its writes; that's deliberate, don't "fix" it into a broken state.
- **The LLM boundary raises langchain's exceptions, not Google's.** `langchain-google-genai` funnels
  every 4xx `ClientError` through `chat_models._handle_client_error` and re-raises it as
  `ChatGoogleGenerativeAIError`, so `google.api_core`'s `ResourceExhausted` never arrives for a
  quota 429 — recover the real status from `exc.__cause__`. 5xx skip that wrapper and still arrive
  as `google.genai.errors.APIError`. Getting this wrong silently disables the extract stage's
  quota early-stop.
- **A null `closing_price` is never written over an existing row.** `get_closing_price` returns
  `None` both for "no price exists" (weekend, holiday) and "the fetch failed", and cannot tell them
  apart. The EOD upsert therefore `$set`s the price only when it has one and uses `$setOnInsert` to
  seed the field as null on a row's first write. Collapsing that back into a plain `$set` lets a
  re-run whose fetch failed erase a price an earlier run stored — and re-running a past day is the
  documented repair path.
- **Every `__main__` entrypoint must call `setup_logging()`** (`backend/core/log.py`). Without it the
  root logger sits at WARNING with no handler, so every `logger.info` — including run summaries — is
  dropped and a successful scheduled run leaves an empty log.
- DB schema change: update `docs/mongodb_schema.md` first, then `scripts/init_db.py`.
- Ruff config lives in `pyproject.toml`: `extend-immutable-calls` whitelists `fastapi.Depends` /
  `fastapi.Query` against B008. Extend that list rather than adding `# noqa` at call sites.
- Config is three `BaseSettings` objects in `core/config.py` (`database_settings`,
  `pipeline_settings`, `api_settings`), all reading the single root `.env`. Add tunables there, not
  as module constants — `W_TICKER` in `formulas.py` is intentionally the exception (modelling
  constant, not configuration).

## State of the repo

**See `STATE.md`** — current implementation status, suite/lint health, known-broken things, the
empty-scaffolding inventory, and doc drift. Read it before assuming a file has content: a large
fraction of this repo is deliberately-seeded 0-byte placeholders, and the test suite is red for
reasons that predate you.

Keep `STATE.md` current when you land something that changes it (a feature goes from empty to
implemented, a listed breakage gets fixed, the test counts move). It is the only file tracking that;
don't duplicate its contents here.

## Workflow

Ticketed branches (`FS-<number>-short-description`), PRs into `main`, CI must pass. Architectural
decisions get an ADR in `docs/adr/`. Never push via the GitHub web upload UI — it commits outside
branch pointers.
