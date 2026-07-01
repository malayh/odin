import uuid
from types import SimpleNamespace

import pytest
from odin.services import graph, mutations, resolution
from odin.services.extraction import Extracted, ExtractedEntity

_CLUSTER = {"bob": 0, "acme": 1, "helios": 2}


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    async def embed(texts):
        out = []
        for t in texts:
            v = [0.0] * 1536
            v[_CLUSTER.get(t.split()[0].lower(), 100)] = 1.0
            out.append(v)
        return out

    monkeypatch.setattr(resolution.embedding, "embed_texts", embed)


def _ex():
    return Extracted(
        entities=[
            ExtractedEntity(name="Bob Smith", type="Person", confidence=0.9),
            ExtractedEntity(name="Bob", type="Person", confidence=0.6),
            ExtractedEntity(name="Acme", type="Org", confidence=0.8),
        ],
        relations=[],
    )


def _fake_confirm(monkeypatch, same):
    async def confirm(prompt, schema, system=None, model=None, max_tokens=None):
        return schema(same=same)

    monkeypatch.setattr(resolution.llm, "complete_json", confirm)


async def test_resolve_merges_similar_confirmed(db_session, monkeypatch):
    _fake_confirm(monkeypatch, True)
    uid = uuid.uuid4()
    merges = await resolution.resolve(db_session, _ex(), uid, str(uuid.uuid4()))

    assert merges == {"person:bob": ("person:bob smith", "Bob Smith", "Person")}
    rows = await mutations.explain(db_session, entity_key="person:bob")
    assert any(r.op == "merge" for r in rows)


async def test_resolve_respects_llm_rejection(db_session, monkeypatch):
    _fake_confirm(monkeypatch, False)
    merges = await resolution.resolve(
        db_session, _ex(), uuid.uuid4(), str(uuid.uuid4())
    )
    assert merges == {}


async def test_resolve_merges_alias_into_existing_graph_entity(db_session, monkeypatch):
    _fake_confirm(monkeypatch, True)
    uid = uuid.uuid4()
    doc = SimpleNamespace(id=uuid.uuid4(), owner_user_id=uid)
    await graph.upsert(
        db_session,
        doc,
        Extracted(entities=[ExtractedEntity(name="Helios Robotics", type="Org", confidence=1.0)]),
        {},
        "x",
    )

    ex = Extracted(entities=[ExtractedEntity(name="Helios", type="Org", confidence=0.9)])
    merges = await resolution.resolve(db_session, ex, uid, str(uuid.uuid4()))
    assert merges == {"org:helios": ("org:helios robotics", "Helios Robotics", "Org")}


async def test_resolve_does_not_merge_dissimilar(db_session, monkeypatch):
    async def confirm(prompt, schema, system=None, model=None, max_tokens=None):
        raise AssertionError("dissimilar pairs should not reach the LLM")

    monkeypatch.setattr(resolution.llm, "complete_json", confirm)
    ex = Extracted(
        entities=[
            ExtractedEntity(name="Bob Smith", type="Person", confidence=0.9),
            ExtractedEntity(name="Acme", type="Org", confidence=0.8),
        ],
        relations=[],
    )
    merges = await resolution.resolve(
        db_session, ex, uuid.uuid4(), str(uuid.uuid4())
    )
    assert merges == {}
