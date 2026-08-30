# FinSense Backend

Setup and development guide for the Python backend. For what FinSense *is* as a product, see the
[root README](../README.md).

The backend is three parts under one `backend/` package:

| Part | What it does |
|---|---|
| `pipeline/` | Scheduled job. Reads RSS, clusters articles into events, scrapes bodies, asks Gemini for sentiment, writes scores to MongoDB. |
| `api/` | FastAPI service. Reads MongoDB and serves the dashboards; handles admin logins and audit corrections. |
| `core/` | Everything both halves share — config, database clients, Pydantic schemas, and the scoring maths. |

One rule holds the design together and is worth learning on day one: **the pipeline never calls the
API, and the API never calls the LLM.** They communicate only through MongoDB. That is why the
scoring formulas live in `core/` — if the pipeline and the API each had their own copy, an admin's
correction and a pipeline run could quietly disagree about the same number.

---

## Prerequisites

- **Python 3.13 or newer.** Not 3.11 or 3.12 — the code uses `datetime.UTC` and `StrEnum` behaviour
  that will fail on older versions.
- **[uv](https://docs.astral.sh/uv/)** for dependency management. Don't use `pip` or `poetry` here;
  the lockfile is `uv.lock`. (A stale `poetry.lock` is still in the repo — ignore it.)
- **A MongoDB Atlas connection string.** Ask the team for one, and make sure **your IP address is
  on the Atlas access list** — otherwise every command below hangs and then times out, with an
  error that doesn't obviously say "network".
- **A Google Gemini API key** ([ai.google.dev](https://ai.google.dev)), only needed if you're
  running the extract stage. The free tier is small and you will hit its rate limit; that's
  expected and handled, see [Troubleshooting](#troubleshooting).

Two things to know before your first run: the pipeline downloads a **~1GB embedding model** on
first use (cached afterwards in `~/.cache/huggingface`), and a full pipeline run makes roughly one
Gemini call per cluster per source — about **80 calls on a cold start**, which will exhaust a
free-tier key in one go.

---

## First-time setup

### 1. Install dependencies

```shell
uv sync --extra dev
```

`--extra dev` adds ruff, pytest and mongomock. Leave it off only for production installs.

### 2. Create your `.env`

There is **one** `.env` file, at the repository root — not in `backend/`. All three settings objects
in `core/config.py` read it. Copy `.env.example` and fill it in; see
[Environment variables](#environment-variables) below for what's required.

**Point `MONGODB_DB_NAME` at a database whose name contains `dev`** (e.g. `FinSense_dev`). Several
scripts refuse to run destructively unless it does, and that guard is the only thing standing
between a stray command and the shared data.

Never commit `.env`. It's gitignored; keep it that way.

### 3. Create the collections and indexes

```shell
uv run python scripts/init_db.py
```

Run once per database. It creates the six collections and their indexes — including the unique ones
that the pipeline's upserts rely on to stay idempotent, so skipping this step doesn't fail loudly,
it just lets duplicates accumulate.

### 4. Seed an admin

```shell
uv run python scripts/seed_admins.py --admin-id adm_you --username you --display-name "Your Name"
```

Prompts for a password on stdin (never as a flag — argv shows up in your shell history and in `ps`).

There is no signup endpoint and no password reset: this script is the only writer of the
`admin_users` collection. **Without this step the audit panel cannot be logged into at all.**
To revoke access later use `--deactivate`, which keeps the row so existing `audit_log` entries
still resolve to a name.

### 5. Check it works

```shell
uv run --extra dev python -m pytest -q     # should be all green
ruff check backend/                        # the only check CI runs today
```

---

## Environment variables

Required — nothing runs without these:

| Variable | Used by | Notes |
|---|---|---|
| `MONGODB_URI` | pipeline + API | Atlas connection string. Unset gives `RuntimeError: MONGODB_URI is not set`. |
| `MONGODB_DB_NAME` | pipeline + API | Defaults to `FinSense`. **Set a `*_dev` name locally.** |
| `LLM_API_KEY` | pipeline | Gemini key. Only the extract stage needs it. |
| `JWT_SECRET_KEY` | API | No default on purpose — a shared default secret is a forgeable admin token. The API **refuses to start** without it. |

Worth tuning while developing — everything here has a working default:

| Variable | Default | What it changes |
|---|---|---|
| `CLUSTER_SIMILARITY_THRESHOLD` | `0.91` | How similar two articles must be to become one event. **Don't lower this casually** — see [`docs/CLUSTERING_THRESHOLD.md`](../docs/CLUSTERING_THRESHOLD.md); 0.88 collapses a 109-article feed into one 56-article blob. |
| `CLUSTER_LOOKBACK_DAYS` | `3` | How far back a new article can join an existing event. Also bounds how long an unfinished cluster keeps being retried. |
| `SCRAPER_DELAY_SECONDS` | `1.0` | Wait between article fetches. Set to `0` to disable pacing (fast, but earns HTTP 429s from VnExpress). |
| `SCRAPER_JITTER_SECONDS` | `0.5` | Random extra wait on top, so repeated runs don't hit a source at identical offsets. |
| `PROMPT_VERSION` | `v3` | Which prompt template the extract stage uses. See [Conventions](#conventions-that-will-bite-you) before changing. |
| `AI_CONFIDENCE_THRESHOLD` | `0.5` | Extractions below this confidence are excluded from a cluster's blended score. |
| `LLM_MODEL_NAME` | `gemini-3.6-flash` | Changing this mid-evolution makes prompt-version comparisons meaningless. |
| `SENTIMENT_BUCKET_THRESHOLD` | `0.2` | Where positive/neutral/negative split on the dashboard gauge. |
| `JWT_EXPIRE_HOURS` | `8` | Admin session length. |
| `CORS_ORIGINS` | `localhost:3000,3001` | Add your frontend's origin here or the browser blocks it at preflight. |

Every other tunable lives in [`backend/core/config.py`](core/config.py), which explains the
reasoning behind each one in comments. Add new settings there — not as module-level constants.

---

## Running things

| Command | What it does |
|---|---|
| `uv run python -m backend.pipeline.main` | One full pipeline run, all five stages. Logs a per-cluster summary. |
| `uv run python -m backend.pipeline.eod_batch.eod_batch` | Roll yesterday (ICT) into `daily_sentiment_history`. |
| `uv run python -m backend.pipeline.eod_batch.eod_batch 2026-08-23` | Re-run a specific past day. |
| `uv run uvicorn backend.api.main:app --reload` | Start the API on `localhost:8000`. |
| `uv run --extra dev python -m pytest -q` | The whole test suite. |
| `ruff check backend/` | Lint. The only thing CI enforces today. |
| `uv run python scripts/init_db.py` | Create collections + indexes. |
| `uv run python scripts/seed_admins.py --admin-id … --username …` | Provision an admin. |
| `uv run python scripts/reset_dev_db.py` | **Destructive.** Wipes pipeline collections. Refuses unless `MONGODB_DB_NAME` contains `dev` or `test`, and asks for confirmation. |
| `uv run python scripts/validate_lexicon.py` | Run after editing anything in `backend/pipeline/lexicon/`. |

With the API running, interactive docs are at **`localhost:8000/docs`** (Swagger) and
**`/redoc`**. `GET /api/health` is the liveness check and touches no database.

The EOD batch is a **separate entrypoint**, not part of `run_pipeline`. It writes one row per VN30
ticker for the target day — a null score where the day had no confident events — and joins the
VNDirect closing price. Events are keyed to the ICT day they were *created*, so re-running a past
day reproduces the score that day originally produced.

---

## Layout

```
backend/
├── core/                     Shared by pipeline AND api — nothing specific to either
│   ├── config.py             All settings, in three BaseSettings objects
│   ├── database.py           Sync client (PyMongo) — pipeline
│   ├── database_async.py     Async client (Motor) — API
│   ├── enums.py              The frozen vocabulary: 30 VN30 tickers, 10 concepts
│   ├── formulas.py           All scoring maths, as pure functions
│   ├── aggregation.py        Blends per-source extractions into an event score
│   ├── schemas/              Pydantic document contracts
│   └── data/                 Ticker → concept weights, ticker display names
│
├── pipeline/
│   ├── main.py               run_pipeline() — the orchestrator
│   ├── stages/               One folder per stage: rss, cluster, scraper, extract, aggregate
│   ├── eod_batch/            Nightly rollup + VNDirect price adapter
│   ├── lexicon/              Vietnamese financial terms, RSS noise keywords
│   └── tests/                unit/ (mocked, fast) and live/ (real Gemini, costs quota)
│
└── api/
    ├── main.py               App, CORS, router registration, health check
    ├── features/             One folder per domain: auth, audit, dashboard, ticker
    └── tests/
```

Every feature folder in `api/features/` has the same three files: `router.py` (HTTP),
`schemas.py` (request/response shapes), `service.py` (logic and database access).

Every stage folder in `pipeline/stages/` has pure helper modules plus a `stage.py` holding the
coordinator. **The coordinator is the only thing that touches MongoDB**; helpers stay pure so they
can be unit-tested without a database.

Adding a file and not sure where it goes? [`docs/FOLDER_STRUCTURE_GUIDANCE.md`](../docs/FOLDER_STRUCTURE_GUIDANCE.md)
is the team's authoritative answer.

---

## How the two halves work

**Pipeline** — `rss → cluster → scraper → extract → aggregate`, run by `run_pipeline()` in
`pipeline/main.py`. Stages hand off through MongoDB rather than in memory, which is what makes a
run resumable: if it dies partway, the next run picks up the unfinished clusters instead of
starting over. Clustering deliberately runs *before* scraping, so only each cluster's
representative article gets its body fetched.

**[`PIPELINE.md`](PIPELINE.md) documents all five stages in detail** — algorithms,
failure handling, and why each decision was made. Read it before changing anything inside a stage.

**API** — four domains under `features/`: `auth` (JWT login), `audit` (the admin review panel),
`dashboard` (market-wide views), `ticker` (per-ticker detail). Ticker scores are computed **at
request time** from `event_clusters`; `daily_sentiment_history` only backs the historical chart.

**[`docs/openapi.yaml`](../docs/openapi.yaml) is the contract source of truth.** The frontend's
TypeScript types are generated from it, so adding a route means editing the spec in the same
change. Spec and implementation are currently at full parity — 14 endpoints each.

---

## Testing

```shell
uv run --extra dev python -m pytest -q                                   # everything
uv run --extra dev python -m pytest backend/pipeline/tests/unit -q       # fast, fully mocked
uv run --extra dev python -m pytest path/to/test.py::TestX::test_y -v    # one test
```

Four conventions you can't guess from reading the code:

**Always pass a fake collection explicitly.** Coordinators take their collection as a parameter
defaulting to `None`, falling back to `get_database()`. That fallback is convenient in production
and dangerous in tests — a test that relies on it **writes to your real database**. Pass the fake.

**There is no pytest-asyncio.** Async services are driven with `asyncio.run()` from ordinary sync
test functions. See `test_dashboard.py` or `test_ticker.py` for the pattern; don't add the
dependency just to avoid it.

**mongomock works for reads, not for everything.** `find`, `$elemMatch`, `$size`, `$exists` and
aggregation pipelines all behave correctly, so prefer mongomock over a hand-written fake — it
executes your query instead of re-asserting your assumptions about it. But it **cannot** do
`bulk_write` (pymongo passes a `sort` argument it rejects) or `array_filters` at all. Code using
either needs a hand-written fake: see `_FakeCollection` in `test_scraper.py` or
`FakeHistoryCollection` in `test_eod_batch.py`. Also build the client with `tz_aware=True` to match
the real one, or you'll get naive datetimes and confusing subtraction errors.

**Live tests cost real Gemini quota.** They're marked `live` and skipped unless `LLM_API_KEY` is in
your **shell environment** — a key in `.env` alone won't trigger them, which is why the suite
reports skips rather than spending money. Run them deliberately:

```shell
uv run --extra dev python -m pytest backend/pipeline/tests/live -m live -v -s
```

Be aware that bare `pytest` does not exclude them by marker (there's no `[tool.pytest.ini_options]`
block yet), so if you ever `export LLM_API_KEY`, a plain test run will start making real calls.

---

## Conventions that will bite you

- **Prompts are append-only.** Never edit an existing `stages/extract/prompts/vN.txt`. Add a new
  version and point `PROMPT_VERSION` at it. Every AI response is stamped with the prompt and model
  version that produced it, so editing history in place makes past extractions incomparable.
- **The rubric documents are pinned to the prompt version by filename.** `v3` loads
  `SENTIMENT_v3.md`, never `SENTIMENT_v2.md`. Reworking a rubric means copying it to the next
  suffix, not editing in place. The shared lexicon JSON *isn't* versioned this way — editing it
  silently changes what an already-stamped version sends, so cut a new `vN.txt` after touching it.
- **`{article_text}` is substituted last.** Scraped article bodies are untrusted input; an article
  containing the literal string `{sentiment_rubric}` must stay literal rather than pulling a
  reference section into itself. Keep that ordering if you add a placeholder.
- **Buckets are derived at read time**, from the stored float, in `core/buckets.py`. Never persist
  a bucket alongside the score it came from.
- **`updated_at` has exactly one writer** — `build_event_cluster` in the cluster stage. It means
  "when an article last joined this event" and drives the dashboard's recency decay. Finishing an
  extraction must never move it.
- **Every `__main__` entrypoint must call `setup_logging()`.** Without it the root logger sits at
  WARNING with no handler and every `logger.info` — including your run summary — is silently
  dropped, so a successful run leaves an empty log.
- **A schema change means `docs/mongodb_schema.md` first, then `scripts/init_db.py`.**
- **New scraper source?** Add an adapter under `stages/scraper/adapters/` and register it in
  `source_client.py`. Nothing else changes.
- **Ruff config lives in `pyproject.toml`.** `extend-immutable-calls` whitelists `fastapi.Depends`
  and `fastapi.Query` against B008 — extend that list rather than adding `# noqa` at call sites.

---

## Troubleshooting

**The API won't start: `JWT_SECRET_KEY is unset — refusing to sign or verify tokens`**
Working as designed. The API checks for the secret before it opens a database connection, so a
misconfigured deploy fails on boot instead of looking healthy and returning a 500 on the first
login. Put a value in `.env`.

**`RuntimeError: MONGODB_URI is not set`**
Your `.env` is missing, in the wrong place (it belongs at the repo root, not in `backend/`), or the
variable is misspelled.

**Everything hangs, then times out**
Almost always the Atlas IP access list. Your current IP has to be on it, and it changes when you
change network.

**The extract stage stops early with `Gemini quota exhausted`**
Also working as designed. On the first HTTP 429 the stage stops rather than burning the rest of the
run on calls that will also fail; already-extracted clusters are saved, and the next run resumes
the rest. The free tier is small — expect this.

**Lots of `No body content for VnExpress` warnings**
The source is rate-limiting you. Fetches are paced by default (`SCRAPER_DELAY_SECONDS` plus
jitter), but repeated runs in quick succession still escalate it. Wait, or raise the delay.

**The first run sits silently for minutes**
It's downloading the ~1GB embedding model. Only happens once per machine.

**A test wrote to the real database**
It fell through to `get_database()` because a fake collection wasn't passed explicitly. See
[Testing](#testing).

---

## Current status

Which parts are actually implemented, what's known-broken, and what's still empty scaffolding is
tracked in **[`STATE.md`](../STATE.md)** — the single place that information lives. Read it before
assuming a file has content: a meaningful fraction of this repo is deliberately-seeded placeholders.
