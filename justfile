# Odin task runner. Run `just` (or `just --list`) to see recipes.
# Loads the root .env into every recipe's environment so alembic/uvicorn/worker
# all see DATABASE_URL etc. even when run from the backend/ subdir.
set dotenv-load := true

# Where alembic lives (alembic.ini uses a relative script_location, so its
# commands must run from this directory).
backend_dir := "backend"

# Show available recipes.
default:
    @just --list

# --- Setup -----------------------------------------------------------------

# Install/sync the whole workspace (backend + cli + dev tools) into .venv.
sync:
    uv sync

# One-shot: infra up, deps synced, schema migrated.
bootstrap: up sync migrate
    @echo "Odin ready. Run 'just serve' and 'just worker' in two terminals."

# --- Infra (Postgres + MinIO via docker compose) ---------------------------

# Start dev infra in the background.
up:
    docker compose up -d

# Stop infra (keeps data volumes).
down:
    docker compose down

# Stop infra AND wipe data volumes (fresh slate).
down-clean:
    docker compose down -v

# Tail infra logs.
logs:
    docker compose logs -f

# --- Server & worker -------------------------------------------------------

# Run the API server with autoreload (http://localhost:8000, /docs, /health).
serve:
    uv run uvicorn odin.main:app --reload --host 0.0.0.0 --port 8000

# Run a background worker (the ingestion pipeline). Use a second terminal.
worker:
    uv run python -m odin.worker

# --- Migrations (Alembic) --------------------------------------------------

# Autogenerate a migration from model changes:  just migration "add chunks"
migration name:
    cd {{backend_dir}} && uv run alembic revision --autogenerate -m "{{name}}"

# Create an empty migration:  just migration-empty "manual tweak"
migration-empty name:
    cd {{backend_dir}} && uv run alembic revision -m "{{name}}"

# Apply all pending migrations.
migrate:
    cd {{backend_dir}} && uv run alembic upgrade head

# Roll back the most recent migration.
downgrade:
    cd {{backend_dir}} && uv run alembic downgrade -1

# Show the current revision / full history.
db-current:
    cd {{backend_dir}} && uv run alembic current
db-history:
    cd {{backend_dir}} && uv run alembic history

# Rebuild the schema from scratch (drops to base, re-applies head).
db-reset:
    cd {{backend_dir}} && uv run alembic downgrade base && uv run alembic upgrade head

# --- CLI -------------------------------------------------------------------

# Run the odin CLI:  just odin ask "what is X" --scope personal
odin *args:
    uv run odin {{args}}

# --- Quality ---------------------------------------------------------------

# Run the test suite (pass extra args:  just test -k chunking).
test *args:
    uv run pytest {{args}}

# Lint, auto-format, and type-check.
lint:
    uv run ruff check .
fmt:
    uv run ruff format .
typecheck:
    uv run mypy backend/odin

# Everything CI would run.
check: lint typecheck test
