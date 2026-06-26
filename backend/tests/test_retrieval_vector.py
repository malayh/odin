import uuid

from odin.models import Chunk, DocState, Document, Embedding, User
from odin.services import embedding, retrieval


def _vec(pairs: dict[int, float]) -> list[float]:
    v = [0.0] * 1536
    for i, val in pairs.items():
        v[i] = val
    return v


async def _seed_doc(session, user, vectors):
    doc = Document(
        owner_user_id=user.id,
        key=f"r-{uuid.uuid4()}.md",
        content_hash=uuid.uuid4().hex,
        version=1,
        state=DocState.indexed,
    )
    session.add(doc)
    await session.flush()
    chunks = []
    for i, vec in enumerate(vectors):
        c = Chunk(
            document_id=doc.id,
            ordinal=i,
            text=f"chunk {i}",
            section_meta={"headings": []},
            char_start=0,
            char_end=1,
        )
        session.add(c)
        await session.flush()
        session.add(Embedding(chunk_id=c.id, vector=vec))
        chunks.append(c)
    await session.flush()
    return doc, chunks


async def test_ranks_by_similarity_and_honors_top_k(db_session, monkeypatch):
    user = User(email=f"r-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    _, (a, b, c) = await _seed_doc(
        db_session, user, [_vec({0: 1.0}), _vec({1: 1.0}), _vec({0: 1.0, 1: 1.0})]
    )

    async def fake_q(texts):
        return [_vec({0: 1.0})]

    monkeypatch.setattr(embedding, "embed_texts", fake_q)

    hits = await retrieval.search(db_session, user.id, "q", top_k=2)

    assert [h.chunk_id for h in hits] == [a.id, c.id]
    assert hits[0].score >= hits[1].score
    assert hits[0].text == "chunk 0"
