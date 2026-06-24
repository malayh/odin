import uuid
from types import SimpleNamespace

from odin.models import GraphMutation, ScopeType
from odin.services import graph, mutations
from odin.tenancy import ScopeSet
from sqlalchemy import select


async def test_log_writes_row(db_session):
    mid = await mutations.log(
        db_session,
        actor="extractor",
        op="entity_create",
        payload={"key": "org:acme"},
        confidence=0.9,
    )
    row = await db_session.get(GraphMutation, mid)
    assert row.actor == "extractor"
    assert row.op == "entity_create"
    assert row.payload == {"key": "org:acme"}
    assert row.confidence == 0.9


async def test_explain_filters_by_entity_key(db_session):
    await mutations.log(db_session, actor="x", op="entity_create", payload={"key": "org:acme"})
    await mutations.log(
        db_session,
        actor="x",
        op="rel_add",
        payload={"subject_key": "org:acme", "object_key": "p:bo"},
    )
    await mutations.log(db_session, actor="x", op="entity_create", payload={"key": "org:other"})

    rows = await mutations.explain(db_session, entity_key="org:acme")
    ops = [r.op for r in rows]
    assert ops == ["entity_create", "rel_add"]


async def test_replay_is_ordered(db_session):
    ids = [
        await mutations.log(db_session, actor="x", op=f"op{i}", payload={"i": i}) for i in range(3)
    ]
    rows = await mutations.replay(db_session)
    seqs = [r.seq for r in rows]
    assert seqs == sorted(seqs)
    assert [r.id for r in rows] == ids
    n = await db_session.scalar(select(GraphMutation.id).order_by(GraphMutation.seq).limit(1))
    assert n == ids[0]


async def test_undo_a_merge_restores_absorbed_entity(worker_db):
    uid = uuid.uuid4()
    d = SimpleNamespace(id=uuid.uuid4(), scope_type=ScopeType.personal, scope_id=uid)
    async with worker_db() as s:
        await graph.upsert_document(s, d)
        await graph.upsert_entity(s, "person:robert", "Robert", "Person")
        await graph.add_mention(s, d, "person:robert", "Robert", "extracted", 0.9, "m")
        await graph.add_mention(s, d, "person:robert", "Bob", "merged", 0.9, "m")
        mid = await mutations.log(
            s,
            actor="resolver",
            op="merge",
            payload={
                "canonical_key": "person:robert",
                "absorbed_key": "person:bob",
                "absorbed_name": "Bob",
                "absorbed_type": "Person",
                "source_doc_id": str(d.id),
                "alias": "Bob",
                "scope_type": "personal",
                "scope_id": str(uid),
                "confidence": 0.9,
                "model": "m",
            },
        )
        await s.commit()

    async with worker_db() as s:
        await mutations.undo(s, mid)
        await s.commit()

    async with worker_db() as s:
        ss = ScopeSet(user_id=uid, roles={})
        bob = await graph.read_entity(s, ss, "person:bob")
        robert = await graph.read_entity(s, ss, "person:robert")

    assert bob is not None
    assert bob["aliases"] == ["Bob"]
    assert robert["aliases"] == ["Robert"]
