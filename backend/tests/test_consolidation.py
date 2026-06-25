import uuid
from types import SimpleNamespace

from odin.models import ScopeType
from odin.services import graph, resolution
from odin.tenancy import ScopeSet


def _doc(scope_id):
    return SimpleNamespace(id=uuid.uuid4(), scope_type=ScopeType.personal, scope_id=scope_id)


def _ent(name, type_):
    return SimpleNamespace(name=name, type=type_, confidence=0.9)


def _rel(subject, predicate, object_):
    return SimpleNamespace(subject=subject, predicate=predicate, object=object_, confidence=0.9)


def _ex(entities, relations):
    return SimpleNamespace(entities=entities, relations=relations)


async def test_merge_nodes_repoints_edges_and_aliases(worker_db):
    uid = uuid.uuid4()
    async with worker_db() as s:
        doc1 = _doc(uid)
        await graph.upsert(
            s,
            doc1,
            _ex(
                [_ent("Helios Robotics", "Org"), _ent("Atlas", "Project")],
                [_rel("Helios Robotics", "builds", "Atlas")],
            ),
            {},
            "m",
        )
        doc2 = _doc(uid)
        await graph.upsert_document(s, doc2)
        await graph.upsert_entity(s, "org:helios", "Helios", "Org")
        await graph.upsert_entity(s, "place:austin", "Austin", "Place")
        await graph.add_mention(s, doc2, "org:helios", "Helios", "extracted", 0.9, "m")
        await graph.add_relationship(
            s, doc2, "org:helios", "LOCATED_IN", "place:austin", "extracted", 0.9, "m"
        )
        await graph.add_relationship(
            s, doc2, "project:atlas", "CREATED_BY", "org:helios", "extracted", 0.9, "m"
        )
        await s.commit()

    async with worker_db() as s:
        await graph.merge_nodes(s, "org:helios robotics", "Helios Robotics", "Org", "org:helios")
        await s.commit()

    async with worker_db() as s:
        scope_set = ScopeSet(user_id=uid, roles={})
        canonical = await graph.read_entity(s, scope_set, "org:helios robotics")
        gone = await graph.read_entity(s, scope_set, "org:helios")
        atlas = await graph.read_entity(s, scope_set, "project:atlas")

    assert gone is None
    assert {"Helios", "Helios Robotics"} <= set(canonical["aliases"])
    out = {(r["predicate"], r["object_key"]) for r in canonical["relationships"]}
    assert ("BUILDS", "project:atlas") in out
    assert ("LOCATED_IN", "place:austin") in out
    incoming = {(r["predicate"], r["object_key"]) for r in atlas["relationships"]}
    assert ("CREATED_BY", "org:helios robotics") in incoming


async def test_consolidate_merges_duplicate_nodes(worker_db, monkeypatch):
    uid = uuid.uuid4()
    async with worker_db() as s:
        doc1 = _doc(uid)
        await graph.upsert(s, doc1, _ex([_ent("Helios Robotics", "Org")], []), {}, "m")
        doc2 = _doc(uid)
        await graph.upsert_document(s, doc2)
        await graph.upsert_entity(s, "org:helios", "Helios", "Org")
        await graph.add_mention(s, doc2, "org:helios", "Helios", "extracted", 0.9, "m")
        await s.commit()

    async def embed(texts):
        return [[1.0, 0.0] for _ in texts]

    async def confirm(prompt, schema, system=None):
        return schema(same=True)

    monkeypatch.setattr(resolution.embedding, "embed_texts", embed)
    monkeypatch.setattr(resolution.llm, "complete_json", confirm)

    async with worker_db() as s:
        merged = await resolution.consolidate(s, "personal", str(uid))
        await s.commit()

    assert merged == 1
    async with worker_db() as s:
        remaining = await graph.list_scope_entities(s, "personal", str(uid))
    assert {e[0] for e in remaining} == {"org:helios robotics"}
