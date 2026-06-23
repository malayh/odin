# Odin — The Seeker of Knowledge

A multi-tenant knowledge index: ingest documents, keep a copy, embed them into a vector
store, derive a provenance-rich knowledge graph, and answer questions over it — all behind
an **API-first** server with a thin CLI client.

- **Design:** see [`spec.md`](./spec.md).
- **Implementation plan (layer by layer):** see [`implementation.md`](./implementation.md).

> Status: **scaffold only.** Modules are stubs; no business logic yet.

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
│       ├── models.py        # ORM models (one file for now)
│       ├── schemas.py       # pydantic API schemas (req/resp share one model)
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
