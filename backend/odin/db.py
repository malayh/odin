"""Async SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from odin.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (see odin.models)."""


_settings = get_settings()
engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
