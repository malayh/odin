FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
COPY cli/ ./cli/

RUN uv sync --frozen --no-dev --package odin-backend

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "odin.main:app", "--host", "0.0.0.0", "--port", "8000"]
