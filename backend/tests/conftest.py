"""Shared test fixtures: ephemeral odin_test DB, async session, and API client."""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from odin.config import get_settings
from odin.db import get_session
from odin.graphdb import cypher
from odin.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_WORKER_TABLES = "graph_mutations, jobs, chunks, documents, memberships, access_tokens, orgs, users"

BACKEND_DIR = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", default=False, help="run tests that hit real providers"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real external providers")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def _test_db_url() -> str:
    base, _, _ = get_settings().database_url.rpartition("/")
    return f"{base}/odin_test"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _test_db_url()


async def _create_and_bootstrap(test_url: str) -> None:
    raw = test_url.replace("+asyncpg", "")
    base, _, name = raw.rpartition("/")
    graph = get_settings().age_graph

    admin = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists and os.getenv("ODIN_TEST_RECREATE"):
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            exists = None
        if not exists:
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()

    db = await asyncpg.connect(raw)
    try:
        await db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await db.execute("CREATE EXTENSION IF NOT EXISTS age")
        await db.execute("LOAD 'age'")
        has_graph = await db.fetchval("SELECT 1 FROM ag_catalog.ag_graph WHERE name = $1", graph)
        if not has_graph:
            await db.execute("SELECT ag_catalog.create_graph($1)", graph)
        await db.execute(f'ALTER DATABASE "{name}" SET search_path = public, ag_catalog')
    finally:
        await db.close()


@pytest.fixture(scope="session", autouse=True)
def _provision_db(test_db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    asyncio.run(_create_and_bootstrap(test_db_url))

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def engine(_provision_db, test_db_url: str):
    from odin.graphdb import register_age

    eng = create_async_engine(test_db_url, poolclass=NullPool)
    register_age(eng.sync_engine)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    app = create_app()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession):
    from odin.seed import seed_admin

    return await seed_admin(db_session, "admin@example.com")


@pytest_asyncio.fixture
async def worker_db(engine, monkeypatch):
    import odin.db
    import odin.worker.handlers
    import odin.worker.queue

    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(odin.db, "SessionLocal", sm)
    monkeypatch.setattr(odin.worker.queue, "SessionLocal", sm)
    monkeypatch.setattr(odin.worker.handlers, "SessionLocal", sm)
    try:
        yield sm
    finally:
        async with sm() as s:
            await cypher(s, get_settings().age_graph, "MATCH (n) DETACH DELETE n")
            await s.commit()
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_WORKER_TABLES} CASCADE"))
