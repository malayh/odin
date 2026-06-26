"""Admin routes: users and tokens (initial-admin only)."""

import uuid

from fastapi import APIRouter, status

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import ForbiddenError, NotFoundError
from odin.models import User
from odin.schemas import (
    CreateTokenIn,
    CreateUserIn,
    TokenCreated,
    TokenOut,
    UserOut,
)
from odin.services import auth as auth_service
from odin.services import users as users_service

router = APIRouter()


def _require_initial_admin(principal: User) -> None:
    if not principal.is_initial_admin:
        raise ForbiddenError("requires an initial admin")


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserIn, principal: PrincipalDep, session: SessionDep) -> UserOut:
    _require_initial_admin(principal)
    user = await users_service.create_user(session, body.email, body.display_name)
    return UserOut.model_validate(user)


@router.post(
    "/users/{user_id}/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED
)
async def create_token(
    user_id: uuid.UUID, body: CreateTokenIn, principal: PrincipalDep, session: SessionDep
) -> TokenCreated:
    _require_initial_admin(principal)
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")
    plaintext, token = await auth_service.issue_token(session, user, body.name, body.expires_at)
    return TokenCreated(
        id=token.id,
        user_id=token.user_id,
        name=token.name,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        token=plaintext,
    )


@router.get("/users/{user_id}/tokens", response_model=list[TokenOut])
async def list_tokens(
    user_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[TokenOut]:
    _require_initial_admin(principal)
    tokens = await auth_service.list_tokens(session, user_id)
    return [TokenOut.model_validate(t) for t in tokens]


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    _require_initial_admin(principal)
    await auth_service.revoke_token(session, token_id)
