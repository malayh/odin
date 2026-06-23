import uuid

import pytest
from odin.errors import ForbiddenError
from odin.models import Membership, Org, Role, ScopeType, User
from odin.tenancy import Scope, can_write, narrow, resolve_scope_set


async def _user(session, email):
    user = User(email=email)
    session.add(user)
    await session.flush()
    return user


async def _org(session, name):
    org = Org(name=name)
    session.add(org)
    await session.flush()
    return org


async def test_resolve_scope_set_from_memberships(db_session):
    user = await _user(db_session, "resolve@example.com")
    org1 = await _org(db_session, "Resolve One")
    org2 = await _org(db_session, "Resolve Two")
    db_session.add(Membership(user_id=user.id, org_id=org1.id, role=Role.admin))
    db_session.add(Membership(user_id=user.id, org_id=org2.id, role=Role.viewer))
    await db_session.flush()

    scope_set = await resolve_scope_set(db_session, user)
    assert scope_set.user_id == user.id
    assert scope_set.org_ids == frozenset({org1.id, org2.id})
    assert scope_set.roles[org1.id] is Role.admin
    assert scope_set.roles[org2.id] is Role.viewer


async def test_narrow_validates_membership(db_session):
    user = await _user(db_session, "narrow@example.com")
    org = await _org(db_session, "Narrow Org")
    db_session.add(Membership(user_id=user.id, org_id=org.id, role=Role.editor))
    await db_session.flush()
    scope_set = await resolve_scope_set(db_session, user)

    assert narrow(scope_set, Scope(ScopeType.org, org.id)).id == org.id
    assert narrow(scope_set, Scope(ScopeType.personal, user.id)).type is ScopeType.personal
    with pytest.raises(ForbiddenError):
        narrow(scope_set, Scope(ScopeType.org, uuid.uuid4()))
    with pytest.raises(ForbiddenError):
        narrow(scope_set, Scope(ScopeType.personal, uuid.uuid4()))


async def test_can_write_by_role(db_session):
    user = await _user(db_session, "write@example.com")
    viewer_org = await _org(db_session, "Viewer Org")
    editor_org = await _org(db_session, "Editor Org")
    db_session.add(Membership(user_id=user.id, org_id=viewer_org.id, role=Role.viewer))
    db_session.add(Membership(user_id=user.id, org_id=editor_org.id, role=Role.editor))
    await db_session.flush()
    scope_set = await resolve_scope_set(db_session, user)

    assert can_write(scope_set, Scope(ScopeType.personal, user.id)) is True
    assert can_write(scope_set, Scope(ScopeType.org, editor_org.id)) is True
    assert can_write(scope_set, Scope(ScopeType.org, viewer_org.id)) is False
