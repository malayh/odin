"""FastAPI dependencies: DB session, current principal (from token), requested scope."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.db import get_session
from odin.errors import AuthError
from odin.models import AccessToken, User
from odin.security import hash_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_principal(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing or malformed Authorization header")
    raw = authorization[7:].strip()
    row = (
        await session.execute(
            select(AccessToken, User)
            .join(User, User.id == AccessToken.user_id)
            .where(AccessToken.token_hash == hash_token(raw))
        )
    ).first()
    if row is None:
        raise AuthError("invalid token")
    token, user = row
    if token.expires_at is not None and token.expires_at < datetime.now(UTC):
        raise AuthError("token expired")
    return user


PrincipalDep = Annotated[User, Depends(current_principal)]
