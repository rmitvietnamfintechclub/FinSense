# FinSense

Sentiment intelligence for the Vietnamese stock market, built from real-time financial news.

FinSense ingests Vietnamese financial news (CafeF, VnExpress), clusters articles that describe
the same market event, and uses an LLM to extract sentiment toward VN30 tickers and sector
concepts. Scores are confidence-weighted and designed to be human-audited, giving a transparent
read on media tone — not a trading signal.

## Project Status

FinSense is under active development. The ingestion and AI-extraction pipeline is functional;
the serving API and web frontends are scaffolded but not yet implemented.

| Component | Status |
|---|---|
| News ingestion → clustering → AI extraction pipeline | ✅ Implemented |
| EOD sentiment history batch job | 🚧 Planned |
| Serving API (FastAPI) | 🚧 Planned |
| Public dashboard | 🚧 Planned |
| Admin audit panel | 🚧 Planned |
| Evaluation harness | 🚧 Partial |

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) for
component-level detail.

## Key Features

- **Multi-source RSS ingestion** with URL normalization and deduplication.
- **Event clustering** — groups articles describing the same event via sentence embeddings and
  incremental cosine-similarity clustering.
- **Centroid and Scraping** choosing representative articles and scrape for full body content
- **LLM-based sentiment extraction** — Google Gemini extracts per-ticker and per-concept
  sentiment from article text, constrained to a fixed VN30/sector vocabulary.
- **Confidence-weighted aggregation** — combines multiple sources per event into a single score,
  excluding low-confidence extractions.
- **Prompt and model versioning** — every AI response is stamped with the prompt and model
  version that produced it, so extraction quality can be tracked over time.
- **Human-in-the-loop audit design** — data model supports approving or correcting AI scores
  with an immutable audit trail (API implementation in progress).

## Tech Stack

**Frontend** (planned)
- Next.js, TypeScript
- Two apps: a public dashboard and an authenticated admin panel, sharing a component library and
  API types generated from the OpenAPI spec

**Backend**
- Python 3.13, FastAPI (serving API — in progress)
- Pydantic v2 for data contracts
- `uv` for dependency management

**Database**
- MongoDB Atlas
- Sync access via PyMongo (pipeline), async access via Motor (API)

**AI/ML**
- Google Gemini (`langchain-google-genai`) for sentiment extraction
- `sentence-transformers` (`intfloat/multilingual-e5-base`) for article embeddings

**DevOps / Infrastructure**
- GitHub Actions for CI (linting; more checks planned)
- Render (planned API hosting)
- MongoDB Atlas (M0 free tier)

## Repository Structure

```
FinSense/
├── backend/
│   ├── core/          Shared config, database clients, schemas, scoring logic
│   ├── pipeline/       RSS → cluster → scrape → extract → aggregate
│   └── api/            Serving API (FastAPI) — in progress
├── frontend/
│   ├── public-dashboard/   Public sentiment dashboard
│   ├── admin-panel/        Authenticated audit panel
│   ├── ui/                 Shared React components
│   └── types/               API types generated from OpenAPI
├── evaluation/          Sentiment extraction benchmarking against a labeled test set
├── docs/                Architecture notes, DB schema, ADRs, OpenAPI spec
├── scripts/             Operational scripts (DB init, seeding, evaluation)
└── .github/workflows/    CI pipelines
```

## System Architecture

FinSense is a monorepo composed of a scheduled data pipeline, a REST API, and two web frontends,
all backed by a shared MongoDB database.

```mermaid
flowchart LR
    A[RSS Sources] --> B[Ingestion Pipeline]
    B --> C[(MongoDB Atlas)]
    C --> D[Serving API]
    D --> E[Public Dashboard]
    D --> F[Admin Panel]
    F -->|audit corrections| C
```

The pipeline runs on a schedule, fetching news, clustering it into events, and enriching each
event with AI-extracted sentiment. The API reads from MongoDB to serve dashboards and handles
admin corrections. Pipeline and API are decoupled — the pipeline never calls the API, and the
API never calls the LLM.

For a deeper architectural breakdown, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
(TODO — not yet written) and [`docs/mongodb_schema.md`](docs/mongodb_schema.md).

## Quick Start

Clone the repository:

```bash
git clone https://github.com/rmitvietnamfintechclub/FinSense.git
cd FinSense
```

Each part of the stack is set up and run independently. Follow the setup instructions in:

- [`backend/README.md`](backend/README.md) — Python environment, database setup, running the
  pipeline and API
- [`frontend/README.md`](frontend/README.md) — Node environment, running the web apps

> **TODO:** `backend/README.md` and `frontend/README.md` do not exist yet in this repository.
> Create them with component-specific setup steps before relying on this Quick Start section.

### Running the Pipeline Locally

The fastest way to verify a local setup end-to-end is to run the ingestion pipeline directly,
without the API or frontend:

1. Create and activate a virtual environment at the project root (Python 3.13+ required):

   ```bash
   uv venv
   source .venv/bin/activate      # macOS/Linux
   # .venv\Scripts\activate       # Windows
   ```

2. Install dependencies into the active environment:

   ```bash
   uv sync
   ```

3. Populate `.env` at the project root (see `.env.example`) — at minimum `MONGODB_URI` and
   `LLM_API_KEY` are required.
4. Reset the dev database. This is a destructive operation, so it only runs if
   `MONGODB_DB_NAME` contains `dev` or `test`, and it asks for confirmation:

   ```bash
   python scripts/reset_dev_db.py
   ```

5. Run the pipeline:

   ```bash
   python -m backend.pipeline.main
   ```

   This executes all five stages (RSS → cluster → scrape → extract → aggregate) once and logs a
   per-cluster summary to stdout.

For the full test suite and API setup (once implemented), see
[`backend/README.md`](backend/README.md).

## Environment Variables

A single `.env` file at the project root configures the backend (pipeline and, eventually, the
API) — see `.env.example` for the required keys (MongoDB connection string, Gemini API key) and
optional pipeline tuning parameters.

The frontend does not yet have its own environment configuration — TODO once implementation
starts.

Never commit `.env` files.

## API Documentation

The API contract is defined in [`docs/openapi.yaml`](docs/openapi.yaml). Once the FastAPI service
is implemented, interactive Swagger UI will be available at `/docs` (and ReDoc at `/redoc`) on
the running API instance. Until then, `docs/openapi.yaml` is the source of truth for available
endpoints, request/response shapes, and authentication.

## Development Workflow

- Work is tracked via ticketed branches (`FS-<number>-short-description`).
- Pull requests target `main` and must pass CI (`ruff check`) before merging.
- See [`.github/pull_request_template.md`](.github/pull_request_template.md) for the PR checklist.
- Architectural decisions are recorded under [`docs/adr/`](docs/adr).

## Contributors

Built by the [RMIT Vietnam Fintech Club](https://github.com/rmitvietnamfintechclub).

TODO — add a contributors list or link to the GitHub contributors graph.

## License

TODO — no license has been specified for this project yet.
