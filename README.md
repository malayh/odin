# Odin — The Seeker of Knowledge

A multi-tenant knowledge index: ingest documents, keep a copy, embed them into a vector
store, derive a provenance-rich knowledge graph, and answer questions over it — all behind
an **API-first** server with a thin CLI client.

- **Design:** see [`spec.md`](./spec.md).
- **Implementation plan (layer by layer):** see [`implementation.md`](./implementation.md).

> Status: **Layer 4 (ask) implemented** — on top of L0–L3, ingestion extracts entities + typed
> relationships (LLM via OpenRouter) and builds a provenance-rich, scope-isolated knowledge graph in
> Apache AGE: canonical entity nodes resolved across documents, every edge carrying scope + provenance,
> and an append-only mutation log. Odin stores all asserted facts faithfully and surfaces conflicting
> ones at query time rather than adjudicating them. The L3 read surface is live — graph expansion in
> retrieval plus a graph API and `odin graph` CLI. `odin ask` now answers questions **grounded in the
> corpus and cited**, refusing (rather than guessing) when the answer is not in your knowledge base;
> retrieval → LLM rerank → scope-filtered context → cited generation. Streaming and the insight layer
> (L5) are still to come.

## Repo layout

```
odin/
├── spec.md                  # design spec
├── pyproject.toml           # uv workspace root (members: backend, cli)
├── docker-compose.yml       # dev infra: Postgres (pgvector+AGE) + MinIO
├── docker/postgres/         # custom Postgres image + init.sql (extensions, graph)
├── backend/                 # the server (package: odin)
│   ├── pyproject.toml
│   ├── alembic.ini, alembic/ # migrations
│   └── odin/
│       ├── main.py          # FastAPI app factory (thin)
│       ├── config.py        # settings (env / .env)
│       ├── db.py            # async SQLAlchemy engine + session
│       ├── models/          # ORM models (one file per resource)
│       ├── schemas/         # pydantic API schemas (one file per resource)
│       ├── security.py, tenancy.py, errors.py, logging.py
│       ├── api/             # thin routers — delegate to services
│       ├── services/        # ALL business logic lives here
│       └── worker/          # separate process: Postgres-backed job queue
└── cli/                     # the CLI (package: odin_cli) — thin client over the API
    └── odin_cli/
        ├── main.py          # Typer app
        ├── client.py, config.py, output.py
        └── commands/        # ask | search | ingest | admin | graph | login
```

## Architecture at a glance

- **Stack:** Python 3.12, async FastAPI + SQLAlchemy 2.0 (asyncpg), Typer CLI, Alembic.
- **One datastore:** Postgres with `pgvector` (embeddings) + Apache AGE (knowledge graph)
  + relational tables (tenancy/metadata).
- **Blobs:** S3-compatible object store (MinIO in dev); originals are content-addressed.
- **Processing:** a Postgres-backed job queue (`FOR UPDATE SKIP LOCKED`) drives the async
  ingestion pipeline in a separate worker process.
- **AI:** cloud-only — Claude for generation/extraction, a hosted embedding model
  (swappable via a model registry), and a hosted reranker.

## Install (production)

Runs the full stack (Postgres + MinIO + API + worker) from pinned images on Docker Hub and
drops a standalone `odin` CLI binary in `~/.odin/bin`. Requires only Docker + Docker Compose.

```bash
curl -fsSL https://raw.githubusercontent.com/malayh/odin/main/install.sh | bash
```

The installer creates `~/.odin/` (config, `.data/` for Postgres + MinIO, the CLI binary),
prompts once for your OpenRouter and OpenAI keys, runs database migrations, bootstraps the
initial admin, and logs the CLI in. Re-running it upgrades in place: it re-pulls the latest
compose file and images and is otherwise idempotent (your `.env`, data, and login are kept).

Prefer to inspect first? Download `install.sh` and run it locally instead of piping to a shell.

## Cutting a release (maintainer)

Components are versioned independently — release just the CLI, just the server, just the
database, or all at once. One-time prerequisites: `docker login` and `gh auth login`.

```bash
./release.sh cli v0.3.0        # build + publish the CLI binary
./release.sh backend v0.2.0    # build + push the API/worker image
./release.sh postgres v1.0.0   # build + push the Postgres (pgvector + AGE) image
./release.sh all v0.1.0        # all three at one version
```

Each image target builds + pushes `malayh/odin-<comp>:<version>` (and `:latest`), pins that
version in `docker-compose.prod.yaml`, commits it, and pushes to `main` — installers read the
pinned compose from there. The `cli` target builds the `odin-linux-x86_64` binary in a
`linux/amd64` container and uploads it to the rolling `cli` GitHub release, which `install.sh`
downloads. Each run also tags the commit (`backend-v*`, `postgres-v*`, `cli-v*`).

## Dev setup

Common tasks are wrapped in a [`justfile`](./justfile) (`just --list` to see them all):

```bash
cp .env.example .env       # fill in ANTHROPIC_API_KEY / OPENAI_API_KEY
just bootstrap             # infra up + uv sync + migrate
just serve                 # API server  → http://localhost:8000  (/health, /docs)
just worker                # ingestion worker (separate terminal)
just odin --help           # the CLI
```

Useful recipes: `just up` / `just down` (infra), `just migration "msg"` +
`just migrate` (Alembic), `just test`, `just check` (lint + types + tests).

<details><summary>…or the raw commands without <code>just</code></summary>

```bash
docker compose up -d                                   # 1. infra (Postgres + MinIO)
uv sync                                                # 2. workspace venv (backend + cli)
cp .env.example .env                                   # 3. config
cd backend && uv run alembic upgrade head && cd ..     # 4. migrations
uv run uvicorn odin.main:app --reload                  # 5. API server
uv run python -m odin.worker                           # 6. worker (separate terminal)
uv run odin --help                                     # 7. CLI
```

</details>

Deployment (k8s/HA) is intentionally out of scope for now.
