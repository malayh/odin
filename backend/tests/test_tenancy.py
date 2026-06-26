import uuid

from odin.models import Document, User
from odin.tenancy import owner_filter
from sqlalchemy import select


async def _user(session, email):
    user = User(email=email)
    session.add(user)
    await session.flush()
    return user


async def _doc(session, owner_id):
    doc = Document(owner_user_id=owner_id, key="t.md", content_hash=uuid.uuid4().hex)
    session.add(doc)
    await session.flush()
    return doc


async def test_owner_filter_excludes_other_users(db_session):
    me = await _user(db_session, "own-me@example.com")
    other = await _user(db_session, "own-other@example.com")
    mine = await _doc(db_session, me.id)
    theirs = await _doc(db_session, other.id)

    visible = set(
        (await db_session.execute(select(Document.id).where(owner_filter(me.id)))).scalars()
    )
    assert mine.id in visible
    assert theirs.id not in visible
