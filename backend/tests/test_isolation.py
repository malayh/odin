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
    doc = Document(
        owner_user_id=owner_id,
        key="iso.md",
        content_hash=uuid.uuid4().hex,
    )
    session.add(doc)
    await session.flush()
    return doc


async def test_owner_filter_excludes_other_users(db_session):
    me = await _user(db_session, "iso-me@example.com")
    other = await _user(db_session, "iso-other@example.com")

    mine = await _doc(db_session, me.id)
    theirs = await _doc(db_session, other.id)

    visible = set(
        (await db_session.execute(select(Document.id).where(owner_filter(me.id)))).scalars()
    )

    assert mine.id in visible
    assert theirs.id not in visible


async def test_vector_search_excludes_other_users(db_session, monkeypatch):
    from odin.models import Chunk, ObjectEmbedding
    from odin.services import embedding, retrieval

    me = await _user(db_session, "vec-me@example.com")
    other = await _user(db_session, "vec-other@example.com")

    async def _seed(owner):
        doc = await _doc(db_session, owner.id)
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
        db_session.add(
            ObjectEmbedding(
                object_type="chunk",
                object_id=str(c.id),
                field="text",
                owner_user_id=owner.id,
                vector=[1.0] + [0.0] * 1535,
            )
        )
        await db_session.flush()
        return c

    my_chunk = await _seed(me)
    their_chunk = await _seed(other)

    async def fake_q(texts):
        return [[1.0] + [0.0] * 1535]

    monkeypatch.setattr(embedding, "embed_texts", fake_q)

    hits = await retrieval.search(db_session, me.id, "q", top_k=10)
    ids = {h.chunk_id for h in hits}

    assert my_chunk.id in ids
    assert their_chunk.id not in ids


async def test_ask_excludes_other_users(db_session, monkeypatch):
    import re

    from odin.models import Chunk, ObjectEmbedding
    from odin.services import answering, embedding, llm

    me = await _user(db_session, "ask-me@example.com")
    other = await _user(db_session, "ask-other@example.com")

    async def _seed(owner, text):
        doc = await _doc(db_session, owner.id)
        c = Chunk(
            document_id=doc.id,
            ordinal=0,
            text=text,
            section_meta={"headings": []},
            char_start=0,
            char_end=len(text),
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(
            ObjectEmbedding(
                object_type="chunk",
                object_id=str(c.id),
                field="text",
                owner_user_id=owner.id,
                vector=[1.0] + [0.0] * 1535,
            )
        )
        await db_session.flush()
        return doc

    mine = await _seed(me, "my secret")
    theirs = await _seed(other, "their secret")

    async def fake_q(texts):
        return [[1.0] + [0.0] * 1535]

    async def fake_llm(prompt, schema, system=None):
        if schema.__name__ == "_Ranking":
            return schema(rankings=[])
        ids = re.findall(r"\[doc ([0-9a-f-]+)\]", prompt)
        return schema(answer="ok", confident=True, used_document_ids=ids + [str(theirs.id)])

    monkeypatch.setattr(embedding, "embed_texts", fake_q)
    monkeypatch.setattr(llm, "complete_json", fake_llm)

    out = await answering.answer(db_session, me.id, "q")
    cited = {c.document_id for c in out.citations}

    assert mine.id in cited
    assert theirs.id not in cited


async def test_graph_traversal_excludes_other_users(worker_db):
    from types import SimpleNamespace

    from odin.services import graph

    a = uuid.uuid4()
    b = uuid.uuid4()

    def _d(owner):
        return SimpleNamespace(id=uuid.uuid4(), owner_user_id=owner)

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
        await graph.upsert(s, _d(a), _ex("Anvil", "Product"), {}, "m")
        await graph.upsert(s, _d(b), _ex("Secret", "Project"), {}, "m")
        await s.commit()

    async with worker_db() as s:
        view_a = await graph.read_entity(s, a, "org:shared")

    objects = {r["object_key"] for r in view_a["relationships"]}
    assert "product:anvil" in objects
    assert "project:secret" not in objects
    assert "Shared" in view_a["aliases"]


async def test_graph_expansion_excludes_other_users(worker_db):
    from types import SimpleNamespace

    from odin.services import graph, retrieval

    a = uuid.uuid4()
    b = uuid.uuid4()

    def _d(owner):
        return SimpleNamespace(id=uuid.uuid4(), owner_user_id=owner)

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
        exp = await retrieval.expand(s, a, [doc_a.id])

    objects = {r.object_key for r in exp.relationships}
    assert "product:anvil" in objects
    assert "project:secret" not in objects
    assert doc_b.id not in exp.linked_document_ids
