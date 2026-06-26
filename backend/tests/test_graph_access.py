import uuid
from types import SimpleNamespace

from odin.services import graph


def _doc(owner):
    return SimpleNamespace(id=uuid.uuid4(), owner_user_id=owner)


def _ent(name, type_, conf=0.9):
    return SimpleNamespace(name=name, type=type_, confidence=conf)


def _rel(s, p, o, conf=0.9):
    return SimpleNamespace(subject=s, predicate=p, object=o, confidence=conf)


def _extracted(entities, relations):
    return SimpleNamespace(entities=entities, relations=relations)


async def test_upsert_persists_provenance_and_scope(worker_db):
    uid = uuid.uuid4()
    d = _doc(uid)
    ex = _extracted([_ent("Acme", "Org"), _ent("Bob", "Person")], [_rel("Bob", "works at", "Acme")])
    async with worker_db() as s:
        await graph.upsert(s, d, ex, {}, "m1")
        await s.commit()
    async with worker_db() as s:
        view = await graph.read_entity(s, uid, "person:bob")
    assert view["name"] == "Bob"
    assert view["type"] == "Person"
    assert view["aliases"] == ["Bob"]
    assert view["relationships"] == [
        {"predicate": "WORKS_AT", "object_key": "org:acme", "source_doc_id": str(d.id)}
    ]


async def test_reingest_replaces_contributions_idempotently(worker_db):
    uid = uuid.uuid4()
    d = _doc(uid)
    ex = _extracted([_ent("Acme", "Org"), _ent("Bob", "Person")], [_rel("Bob", "works at", "Acme")])

    async def _counts():
        async with worker_db() as s:
            m = await graph._cy(
                s,
                "MATCH (:Document {doc_id:$d})-[m:MENTIONS]->() RETURN count(m)",
                {"d": str(d.id)},
                columns=("c",),
            )
            r = await graph._cy(
                s,
                "MATCH ()-[r:REL]->() WHERE r.source_doc_id=$d RETURN count(r)",
                {"d": str(d.id)},
                columns=("c",),
            )
            return m[0][0], r[0][0]

    async with worker_db() as s:
        await graph.delete_document_contributions(s, str(d.id))
        await graph.upsert(s, d, ex, {}, "m1")
        await s.commit()
    first = await _counts()
    async with worker_db() as s:
        await graph.delete_document_contributions(s, str(d.id))
        await graph.upsert(s, d, ex, {}, "m1")
        await s.commit()
    second = await _counts()
    assert first == second == (2, 1)
