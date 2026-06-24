import uuid

import pytest
from odin.config import get_settings
from odin.models import Chunk, DocState, Document, Embedding, ScopeType, User
from odin.services import embedding
from sqlalchemy import func, select


class _Resp:
    def __init__(self, vectors):
        self.data = [type("D", (), {"embedding": v})() for v in vectors]


class _FakeEmbeddings:
    def __init__(self, parent):
        self.parent = parent

    def create(self, model, input):
        self.parent.calls.append(list(input))
        if self.parent.fail_times > 0:
            self.parent.fail_times -= 1
            raise RuntimeError("transient")
        return _Resp([[float(len(t))] * 4 for t in input])


class _FakeClient:
    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times
        self.embeddings = _FakeEmbeddings(self)


async def test_embed_texts_batches(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(embedding, "_client", lambda: fake)
    monkeypatch.setattr(embedding, "_BATCH", 2)
    out = await embedding.embed_texts(["a", "b", "c"])
    assert len(out) == 3
    assert [len(c) for c in fake.calls] == [2, 1]


async def test_embed_texts_retries_then_succeeds(monkeypatch):
    fake = _FakeClient(fail_times=2)
    monkeypatch.setattr(embedding, "_client", lambda: fake)
    out = await embedding.embed_texts(["x"])
    assert len(out) == 1
    assert len(fake.calls) == 3


async def test_embed_texts_raises_after_max_attempts(monkeypatch):
    fake = _FakeClient(fail_times=99)
    monkeypatch.setattr(embedding, "_client", lambda: fake)
    with pytest.raises(RuntimeError):
        await embedding.embed_texts(["x"])


async def test_embed_chunks_inserts_one_vector_per_chunk(db_session, monkeypatch):
    user = User(email=f"emb-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    doc = Document(
        owner_user_id=user.id,
        scope_type=ScopeType.personal,
        scope_id=user.id,
        key="e.md",
        content_hash="h",
        version=1,
        state=DocState.pending,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add_all(
        Chunk(
            document_id=doc.id,
            ordinal=i,
            text=f"chunk {i}",
            section_meta={"headings": []},
            char_start=0,
            char_end=1,
        )
        for i in range(3)
    )
    await db_session.flush()

    async def fake_embed_texts(texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]

    monkeypatch.setattr(embedding, "embed_texts", fake_embed_texts)
    await embedding.embed_chunks(db_session, doc.id)

    n = await db_session.scalar(select(func.count()).select_from(Embedding))
    assert n == 3
    rows = (await db_session.execute(select(Embedding))).scalars().all()
    for r in rows:
        assert len(r.vector) == 1536


@pytest.mark.live
async def test_embed_texts_live():
    out = await embedding.embed_texts(["hello world"])
    assert len(out) == 1
    assert len(out[0]) == get_settings().embedding_dimensions
