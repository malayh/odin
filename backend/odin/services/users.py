"""User management: create users (invite-only onboarding)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import ConflictError
from odin.models import User


async def create_user(session: AsyncSession, email: str, display_name: str | None = None) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError(f"user already exists: {email}")
    user = User(email=email, display_name=display_name)
    session.add(user)
    await session.commit()
    return user
