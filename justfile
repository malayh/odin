set dotenv-load := true
backend_dir := "backend"

default:
    @just --list

sync:
    uv sync --all-packages



serve:
    uv run uvicorn odin.main:app --reload --host 0.0.0.0 --port 8000

worker:
    uv run python -m odin.worker

seed-admin email:
    cd {{backend_dir}} && uv run python -m odin.seed "{{email}}"


migration name:
    cd {{backend_dir}} && uv run alembic revision --autogenerate -m "{{name}}"

migration-empty name:
    cd {{backend_dir}} && uv run alembic revision -m "{{name}}"

migrate:
    cd {{backend_dir}} && uv run alembic upgrade head

downgrade:
    cd {{backend_dir}} && uv run alembic downgrade -1


odin *args:
    uv run odin {{args}}

test *args:
    uv run pytest {{args}}

lint:
    uv run ruff check .
fmt:
    uv run ruff format .
typecheck:
    uv run mypy backend/odin

check: lint typecheck test
