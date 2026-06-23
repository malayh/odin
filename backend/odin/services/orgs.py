"""Orgs and membership: create orgs, manage members and roles; invite-only onboarding."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import ConflictError, NotFoundError
from odin.models import Membership, Org, Role, User


async def create_user(session: AsyncSession, email: str, display_name: str | None = None) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError(f"user already exists: {email}")
    user = User(email=email, display_name=display_name)
    session.add(user)
    await session.commit()
    return user


async def create_org(session: AsyncSession, name: str, creator: User) -> Org:
    existing = await session.scalar(select(Org).where(Org.name == name))
    if existing is not None:
        raise ConflictError(f"org already exists: {name}")
    org = Org(name=name)
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=creator.id, org_id=org.id, role=Role.admin))
    await session.commit()
    return org


async def add_member(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> Membership:
    await _require_org(session, org_id)
    await _require_user(session, user_id)
    existing = await _find_membership(session, org_id, user_id)
    if existing is not None:
        raise ConflictError("user is already a member of that org")
    membership = Membership(user_id=user_id, org_id=org_id, role=role)
    session.add(membership)
    await session.commit()
    return membership


async def set_role(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> Membership:
    membership = await _find_membership(session, org_id, user_id)
    if membership is None:
        raise NotFoundError("membership not found")
    membership.role = role
    await session.commit()
    return membership


async def remove_member(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    membership = await _find_membership(session, org_id, user_id)
    if membership is None:
        raise NotFoundError("membership not found")
    await session.delete(membership)
    await session.commit()


async def _find_membership(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    return await session.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


async def _require_org(session: AsyncSession, org_id: uuid.UUID) -> Org:
    org = await session.get(Org, org_id)
    if org is None:
        raise NotFoundError("org not found")
    return org


async def _require_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return user
