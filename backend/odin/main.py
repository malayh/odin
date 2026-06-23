"""FastAPI application factory for the Odin API server.

The API is the product; routers stay thin and delegate to odin.services.*.
Run with: ``uv run uvicorn odin.main:app --reload``
"""

from fastapi import FastAPI

from odin.api import admin, ask, auth, graph, ingest, jobs, search

API_V1 = "/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Odin", version="0.0.0", summary="The seeker of knowledge")

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix=f"{API_V1}/auth", tags=["auth"])
    app.include_router(ingest.router, prefix=f"{API_V1}/ingest", tags=["ingest"])
    app.include_router(search.router, prefix=f"{API_V1}/search", tags=["search"])
    app.include_router(ask.router, prefix=f"{API_V1}/ask", tags=["ask"])
    app.include_router(graph.router, prefix=f"{API_V1}/graph", tags=["graph"])
    app.include_router(jobs.router, prefix=f"{API_V1}/jobs", tags=["jobs"])
    app.include_router(admin.router, prefix=f"{API_V1}/admin", tags=["admin"])
    return app


app = create_app()
