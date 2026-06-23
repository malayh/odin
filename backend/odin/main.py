"""FastAPI application factory for the Odin API server.

The API is the product; routers stay thin and delegate to odin.services.*.
Run with: ``uv run uvicorn odin.main:app --reload``
"""

from fastapi import FastAPI

from odin.api import admin, ask, auth, graph, ingest, jobs, search
from odin.errors import register_error_handlers
from odin.logging import RequestIDMiddleware, configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Odin", version="0.0.0", summary="The seeker of knowledge")
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(ask.router, prefix="/ask", tags=["ask"])
    app.include_router(graph.router, prefix="/graph", tags=["graph"])
    app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])
    return app


app = create_app()
