"""Admin routes: orgs, members, roles (Admin/Editor/Viewer), scopes."""

import uuid

from fastapi import APIRouter, status

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import ForbiddenError, NotFoundError
from odin.models import Role, User
from odin.schemas import (
    AddMemberIn,
    CreateOrgIn,
    CreateTokenIn,
    CreateUserIn,
    MembershipOut,
    OrgOut,
    SetRoleIn,
    TokenCreated,
    TokenOut,
    UserOut,
)
from odin.services import auth as auth_service
from odin.services import orgs as orgs_service
from odin.tenancy import resolve_scope_set

router = APIRouter()


def _require_initial_admin(principal: User) -> None:
    if not principal.is_initial_admin:
        raise ForbiddenError("requires an initial admin")


async def _require_org_admin(session: SessionDep, principal: User, org_id: uuid.UUID) -> None:
    if principal.is_initial_admin:
        return
    scope_set = await resolve_scope_set(session, principal)
    if scope_set.roles.get(org_id) is not Role.admin:
        raise ForbiddenError("requires org admin")


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserIn, principal: PrincipalDep, session: SessionDep) -> UserOut:
    _require_initial_admin(principal)
    user = await orgs_service.create_user(session, body.email, body.display_name)
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


@router.post("/orgs", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(body: CreateOrgIn, principal: PrincipalDep, session: SessionDep) -> OrgOut:
    _require_initial_admin(principal)
    org = await orgs_service.create_org(session, body.name, principal)
    return OrgOut.model_validate(org)


@router.post(
    "/orgs/{org_id}/members", response_model=MembershipOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    org_id: uuid.UUID, body: AddMemberIn, principal: PrincipalDep, session: SessionDep
) -> MembershipOut:
    await _require_org_admin(session, principal, org_id)
    membership = await orgs_service.add_member(session, org_id, body.user_id, body.role)
    return MembershipOut.model_validate(membership)


@router.put("/orgs/{org_id}/members/{user_id}", response_model=MembershipOut)
async def set_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: SetRoleIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> MembershipOut:
    await _require_org_admin(session, principal, org_id)
    membership = await orgs_service.set_role(session, org_id, user_id, body.role)
    return MembershipOut.model_validate(membership)


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID, user_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await _require_org_admin(session, principal, org_id)
    await orgs_service.remove_member(session, org_id, user_id)
