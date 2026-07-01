"""FastAPI application factory for the Odin API server.

The API is the product; routers stay thin and delegate to odin.services.*.
Run with: ``uv run uvicorn odin.main:app --reload``
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odin.api import admin, ask, auth, documents, graph, ingest, jobs, search, sleep
from odin.errors import register_error_handlers
from odin.logging import RequestIDMiddleware, configure_logging
from odin.worker.app import app as queue_app


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with queue_app.open_async():
        yield


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Odin", version="0.0.0", summary="The seeker of knowledge", lifespan=_lifespan
    )
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
    app.include_router(documents.router, prefix="/documents", tags=["documents"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(ask.router, prefix="/ask", tags=["ask"])
    app.include_router(graph.router, prefix="/graph", tags=["graph"])
    app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])
    app.include_router(sleep.router, tags=["sleep"])
    return app


app = create_app()
