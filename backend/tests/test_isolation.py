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
        key="iso.md",
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


async def test_vector_search_excludes_other_users(db_session, monkeypatch):
    from odin.models import Chunk, Embedding
    from odin.services import embedding, retrieval

    me = await _user(db_session, "vec-me@example.com")
    other = await _user(db_session, "vec-other@example.com")

    async def _seed(owner):
        doc = await _doc(db_session, owner.id, ScopeType.personal, owner.id)
        c = Chunk(
            document_id=doc.id,
            ordinal=0,
            text="secret",
            section_meta={"headings": []},
            char_start=0,
            char_end=1,
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(Embedding(chunk_id=c.id, vector=[1.0] + [0.0] * 1535))
        await db_session.flush()
        return c

    my_chunk = await _seed(me)
    their_chunk = await _seed(other)

    async def fake_q(texts):
        return [[1.0] + [0.0] * 1535]

    monkeypatch.setattr(embedding, "embed_texts", fake_q)

    scope_set = await resolve_scope_set(db_session, me)
    hits = await retrieval.search(db_session, scope_set, "q", None, top_k=10)
    ids = {h.chunk_id for h in hits}

    assert my_chunk.id in ids
    assert their_chunk.id not in ids
