from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from odin.errors import NotFoundError, register_error_handlers
from odin.logging import RequestIDMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)

    @app.get("/known")
    async def known() -> dict:
        raise NotFoundError("nope")

    @app.get("/boom")
    async def boom() -> dict:
        raise ValueError("kaboom")

    return app


def _client() -> AsyncClient:
    transport = ASGITransport(app=_app(), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_known_error_maps_to_envelope():
    async with _client() as c:
        r = await c.get("/known")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["type"] == "not_found"
    assert body["error"]["message"] == "nope"
    assert body["error"]["request_id"]
    assert r.headers["x-request-id"]


async def test_unhandled_error_maps_to_500_without_leaking():
    async with _client() as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["type"] == "internal_error"
    assert "request_id" in body["error"]
    assert "kaboom" not in r.text
    assert "Traceback" not in r.text
