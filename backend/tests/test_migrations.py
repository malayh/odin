import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from odin.models import DocState, Document, Membership, Org, Role, ScopeType, User
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = {
    "users",
    "orgs",
    "memberships",
    "access_tokens",
    "documents",
    "chunks",
    "jobs",
    "embeddings",
    "graph_mutations",
}


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _public_tables(url: str) -> set[str]:
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    try:
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}
    finally:
        await conn.close()


def test_upgrade_downgrade_round_trip(test_db_url):
    cfg = _cfg(test_db_url)
    assert TABLES <= asyncio.run(_public_tables(test_db_url))
    command.downgrade(cfg, "base")
    assert not (TABLES & asyncio.run(_public_tables(test_db_url)))
    command.upgrade(cfg, "head")
    assert TABLES <= asyncio.run(_public_tables(test_db_url))


async def test_membership_unique_constraint(db_session):
    user = User(email="dup@example.com")
    org = Org(name="Dup Org")
    db_session.add_all([user, org])
    await db_session.flush()

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=Role.admin))
    await db_session.flush()

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=Role.editor))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_active_key_is_unique_per_scope(db_session):
    user = User(email="key@example.com")
    db_session.add(user)
    await db_session.flush()

    def _doc(content_hash: str, version: int) -> Document:
        return Document(
            owner_user_id=user.id,
            scope_type=ScopeType.personal,
            scope_id=user.id,
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
