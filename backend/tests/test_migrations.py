import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from odin.models import Membership, Org, Role, User
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = {"users", "orgs", "memberships", "access_tokens", "documents"}


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
