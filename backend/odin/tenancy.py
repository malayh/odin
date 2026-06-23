"""Scope/tenancy primitives: resolve a caller scope set; access guards (no cross-scope leakage)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import ForbiddenError, ValidationError
from odin.models import Document, Membership, Role, ScopeType, User


@dataclass(frozen=True)
class Scope:
    type: ScopeType
    id: uuid.UUID

    def wire(self) -> str:
        return f"{self.type.value}:{self.id}"

    @classmethod
    def parse(cls, raw: str, self_user_id: uuid.UUID) -> "Scope":
        if raw == "personal":
            return cls(ScopeType.personal, self_user_id)
        kind, _, ident = raw.partition(":")
        if kind == "org" and ident:
            try:
                return cls(ScopeType.org, uuid.UUID(ident))
            except ValueError as e:
                raise ValidationError(f"invalid scope: {raw!r}") from e
        raise ValidationError(f"invalid scope: {raw!r}")


@dataclass(frozen=True)
class ScopeSet:
    user_id: uuid.UUID
    roles: dict[uuid.UUID, Role]

    @property
    def org_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(self.roles)


async def resolve_scope_set(session: AsyncSession, user: User) -> ScopeSet:
    rows = (
        await session.execute(
            select(Membership.org_id, Membership.role).where(Membership.user_id == user.id)
        )
    ).all()
    return ScopeSet(user_id=user.id, roles={org_id: role for org_id, role in rows})


def narrow(scope_set: ScopeSet, requested: Scope) -> Scope:
    if requested.type is ScopeType.personal:
        if requested.id != scope_set.user_id:
            raise ForbiddenError("cannot access another user's personal scope")
        return requested
    if requested.id not in scope_set.roles:
        raise ForbiddenError("not a member of that org")
    return requested


def scope_filter(scope_set: ScopeSet, only: Scope | None = None) -> ColumnElement[bool]:
    if only is not None:
        return and_(Document.scope_type == only.type, Document.scope_id == only.id)
    personal = and_(
        Document.scope_type == ScopeType.personal, Document.scope_id == scope_set.user_id
    )
    if not scope_set.org_ids:
        return personal
    org = and_(Document.scope_type == ScopeType.org, Document.scope_id.in_(scope_set.org_ids))
    return or_(personal, org)


def can_write(scope_set: ScopeSet, scope: Scope) -> bool:
    if scope.type is ScopeType.personal:
        return scope.id == scope_set.user_id
    return scope_set.roles.get(scope.id) in (Role.admin, Role.editor)


def can_read(scope_set: ScopeSet, scope: Scope) -> bool:
    if scope.type is ScopeType.personal:
        return scope.id == scope_set.user_id
    return scope.id in scope_set.org_ids
