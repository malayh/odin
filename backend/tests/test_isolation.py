import uuid

from odin.models import Document, ScopeType, User
from odin.tenancy import resolve_scope_set, scope_filter
from sqlalchemy import select


async def _user(session, email):
    user = User(email=email)
    session.add(user)
    await session.flush()
    return user


async def _doc(session, owner_id, scope_type, scope_id):
    doc = Document(
        owner_user_id=owner_id,
        scope_type=scope_type,
        scope_id=scope_id,
        content_hash=uuid.uuid4().hex,
    )
    session.add(doc)
    await session.flush()
    return doc


async def test_scope_filter_excludes_other_users_and_unjoined_orgs(db_session):
    me = await _user(db_session, "iso-me@example.com")
    other = await _user(db_session, "iso-other@example.com")
    unjoined_org = uuid.uuid4()

    mine = await _doc(db_session, me.id, ScopeType.personal, me.id)
    theirs = await _doc(db_session, other.id, ScopeType.personal, other.id)
    foreign_org_doc = await _doc(db_session, other.id, ScopeType.org, unjoined_org)

    scope_set = await resolve_scope_set(db_session, me)
    visible = set(
        (await db_session.execute(select(Document.id).where(scope_filter(scope_set)))).scalars()
    )

    assert mine.id in visible
    assert theirs.id not in visible
    assert foreign_org_doc.id not in visible
