"""Auth: issue/verify personal access tokens; resolve the calling principal."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import NotFoundError
from odin.models import AccessToken, User
from odin.security import generate_token, hash_token


async def issue_token(
    session: AsyncSession,
    user: User,
    name: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, AccessToken]:
    plaintext = generate_token()
    token = AccessToken(
        user_id=user.id, token_hash=hash_token(plaintext), name=name, expires_at=expires_at
    )
    session.add(token)
    await session.commit()
    return plaintext, token


async def list_tokens(session: AsyncSession, user_id: uuid.UUID) -> Sequence[AccessToken]:
    result = await session.execute(
        select(AccessToken).where(AccessToken.user_id == user_id).order_by(AccessToken.created_at)
    )
    return result.scalars().all()


async def revoke_token(session: AsyncSession, token_id: uuid.UUID) -> None:
    token = await session.get(AccessToken, token_id)
    if token is None:
        raise NotFoundError("token not found")
    await session.delete(token)
    await session.commit()
