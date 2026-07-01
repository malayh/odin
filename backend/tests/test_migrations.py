import asyncio
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from odin.models import DocState, Document, User
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = {
    "users",
    "access_tokens",
    "documents",
    "chunks",
    "jobs",
    "embeddings",
    "graph_mutations",
    "sleep_runs",
}


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _public_tables(url: str) -> set[str]:
    conn = await psycopg.AsyncConnection.connect(url.replace("+psycopg", ""), autocommit=True)
    try:
        cur = await conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        rows = await cur.fetchall()
        return {r[0] for r in rows}
    finally:
        await conn.close()


def test_upgrade_downgrade_round_trip(test_db_url):
    cfg = _cfg(test_db_url)
    assert TABLES <= asyncio.run(_public_tables(test_db_url))
    command.downgrade(cfg, "base")
    assert not (TABLES & asyncio.run(_public_tables(test_db_url)))
    command.upgrade(cfg, "head")
    assert TABLES <= asyncio.run(_public_tables(test_db_url))


async def test_active_key_is_unique_per_owner(db_session):
    user = User(email="key@example.com")
    db_session.add(user)
    await db_session.flush()

    def _doc(content_hash: str, version: int) -> Document:
        return Document(
            owner_user_id=user.id,
            key="dup.md",
            content_hash=content_hash,
            version=version,
            state=DocState.pending,
        )

    db_session.add(_doc("a", 1))
    await db_session.flush()
    db_session.add(_doc("b", 2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
