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


async def test_graph_traversal_excludes_other_users(worker_db):
    from types import SimpleNamespace

    from odin.models import ScopeType
    from odin.services import graph
    from odin.tenancy import ScopeSet

    a = uuid.uuid4()
    b = uuid.uuid4()

    def _doc(scope_id):
        return SimpleNamespace(id=uuid.uuid4(), scope_type=ScopeType.personal, scope_id=scope_id)

    def _ent(name, type_):
        return SimpleNamespace(name=name, type=type_, confidence=0.9)

    def _ex(other_name, other_type):
        return SimpleNamespace(
            entities=[_ent("Shared", "Org"), _ent(other_name, other_type)],
            relations=[
                SimpleNamespace(
                    subject="Shared", predicate="builds", object=other_name, confidence=0.9
                )
            ],
        )

    async with worker_db() as s:
        await graph.upsert(s, _doc(a), _ex("Anvil", "Product"), {}, "m")
        await graph.upsert(s, _doc(b), _ex("Secret", "Project"), {}, "m")
        await s.commit()

    async with worker_db() as s:
        view_a = await graph.read_entity(s, ScopeSet(user_id=a, roles={}), "org:shared")

    objects = {r["object_key"] for r in view_a["relationships"]}
    assert "product:anvil" in objects
    assert "project:secret" not in objects
    assert "Shared" in view_a["aliases"]


async def test_graph_expansion_excludes_other_users(worker_db):
    from types import SimpleNamespace

    from odin.services import graph, retrieval
    from odin.tenancy import ScopeSet

    a = uuid.uuid4()
    b = uuid.uuid4()

    def _d(scope_id):
        return SimpleNamespace(id=uuid.uuid4(), scope_type=ScopeType.personal, scope_id=scope_id)

    def _ent(name, type_):
        return SimpleNamespace(name=name, type=type_, confidence=0.9)

    def _ex(other_name, other_type):
        return SimpleNamespace(
            entities=[_ent("Shared", "Org"), _ent(other_name, other_type)],
            relations=[
                SimpleNamespace(
                    subject="Shared", predicate="builds", object=other_name, confidence=0.9
                )
            ],
        )

    doc_a = _d(a)
    doc_b = _d(b)

    async with worker_db() as s:
        await graph.upsert(s, doc_a, _ex("Anvil", "Product"), {}, "m")
        await graph.upsert(s, doc_b, _ex("Secret", "Project"), {}, "m")
        await s.commit()

    async with worker_db() as s:
        exp = await retrieval.expand(s, ScopeSet(user_id=a, roles={}), [doc_a.id])

    objects = {r.object_key for r in exp.relationships}
    assert "product:anvil" in objects
    assert "project:secret" not in objects
    assert doc_b.id not in exp.linked_document_ids
