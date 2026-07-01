import uuid
from types import SimpleNamespace

import pytest
from odin.models import ObjectEmbedding, User
from odin.scripts.backfill_object_embeddings import backfill_owner
from odin.services import embedding, graph, ontology
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    async def fake(texts):
        return [[float(len(t))] + [0.0] * 1535 for t in texts]

    monkeypatch.setattr(embedding, "embed_texts", fake)


async def _user(session):
    u = User(email=f"oe-{uuid.uuid4()}@example.com")
    session.add(u)
    await session.flush()
    return u


async def _entity_ids(session, owner):
    rows = await session.execute(
        select(ObjectEmbedding.object_id).where(
            ObjectEmbedding.object_type == "entity",
            ObjectEmbedding.owner_user_id == owner,
        )
    )
    return set(rows.scalars().all())


async def test_create_entity_writes_embedding(db_session):
    u = await _user(db_session)
    await graph.create_entity(db_session, u.id, "Org", "Helios Robotics")
    key = ontology.entity_key("Helios Robotics", "Org")
    assert await _entity_ids(db_session, u.id) == {key}


async def test_drop_entity_deletes_embedding(db_session):
    u = await _user(db_session)
    await graph.create_entity(db_session, u.id, "Org", "Helios")
    key = ontology.entity_key("Helios", "Org")
    await graph.drop_entity(db_session, u.id, key)
    assert await _entity_ids(db_session, u.id) == set()


async def test_rename_entity_moves_embedding(db_session):
    u = await _user(db_session)
    await graph.create_entity(db_session, u.id, "Org", "Helios")
    old = ontology.entity_key("Helios", "Org")
    await graph.rename_entity(db_session, u.id, old, "Helios Robotics")
    new = ontology.entity_key("Helios Robotics", "Org")
    ids = await _entity_ids(db_session, u.id)
    assert new in ids
    assert old not in ids


async def test_merge_nodes_deletes_absorbed_embedding(db_session):
    u = await _user(db_session)
    await graph.create_entity(db_session, u.id, "Org", "Helios Robotics")
    await graph.create_entity(db_session, u.id, "Org", "Helios")
    canon = ontology.entity_key("Helios Robotics", "Org")
    absorbed = ontology.entity_key("Helios", "Org")
    await graph.merge_nodes(db_session, canon, "Helios Robotics", "Org", absorbed, str(u.id))
    ids = await _entity_ids(db_session, u.id)
    assert canon in ids
    assert absorbed not in ids


async def test_upsert_on_conflict_updates_vector(db_session):
    u = await _user(db_session)
    await embedding.upsert_object_embeddings(db_session, "entity", "name", u.id, [("k:1", "ab")])
    await embedding.upsert_object_embeddings(db_session, "entity", "name", u.id, [("k:1", "abcd")])
    rows = (
        await db_session.execute(
            select(ObjectEmbedding).where(ObjectEmbedding.object_id == "k:1")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].vector[0]) == 4.0


async def test_backfill_embeds_missing(db_session):
    u = await _user(db_session)
    doc = SimpleNamespace(id=uuid.uuid4(), owner_user_id=u.id)
    ext = SimpleNamespace(
        entities=[SimpleNamespace(name="Helios", type="Org", confidence=0.9)],
        relations=[],
        objectives=[],
    )
    await graph.upsert(db_session, doc, ext, {}, "m")
    key = ontology.entity_key("Helios", "Org")
    await embedding.delete_object_embeddings(db_session, "entity", key)
    assert await _entity_ids(db_session, u.id) == set()
    n = await backfill_owner(db_session, u.id)
    assert n == 1
    assert await _entity_ids(db_session, u.id) == {key}
