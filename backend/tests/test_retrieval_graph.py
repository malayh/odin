import uuid
from types import SimpleNamespace

from odin.models import ScopeType
from odin.services import graph, retrieval
from odin.tenancy import ScopeSet


def _doc(scope_id):
    return SimpleNamespace(id=uuid.uuid4(), scope_type=ScopeType.personal, scope_id=scope_id)


def _ent(name, type_):
    return SimpleNamespace(name=name, type=type_, confidence=0.9)


def _rel(subject, predicate, object_):
    return SimpleNamespace(subject=subject, predicate=predicate, object=object_, confidence=0.9)


def _ex(entities, relations):
    return SimpleNamespace(entities=entities, relations=relations)


async def test_expand_pulls_entities_relationships_and_linked_docs(worker_db):
    user = uuid.uuid4()
    scope_set = ScopeSet(user_id=user, roles={})
    doc_a = _doc(user)
    doc_b = _doc(user)

    async with worker_db() as s:
        await graph.upsert(
            s,
            doc_a,
            _ex(
                [_ent("Mara Vance", "Person"), _ent("Helios", "Org")],
                [_rel("Mara Vance", "works_at", "Helios")],
            ),
            {},
            "m",
        )
        await graph.upsert(
            s,
            doc_b,
            _ex(
                [_ent("Helios", "Org"), _ent("Atlas", "Project")],
                [_rel("Helios", "builds", "Atlas")],
            ),
            {},
            "m",
        )
        await s.commit()

    async with worker_db() as s:
        exp = await retrieval.expand(s, scope_set, [doc_a.id])

    assert {e.key for e in exp.entities} == {"person:mara vance", "org:helios"}
    rels = {(r.predicate, r.object_key) for r in exp.relationships}
    assert ("WORKS_AT", "org:helios") in rels
    assert ("BUILDS", "project:atlas") in rels
    assert doc_b.id in exp.linked_document_ids
    assert doc_a.id not in exp.linked_document_ids


async def test_expand_respects_fanout_caps(worker_db):
    user = uuid.uuid4()
    scope_set = ScopeSet(user_id=user, roles={})
    doc = _doc(user)

    async with worker_db() as s:
        await graph.upsert(
            s, doc, _ex([_ent(f"E{i}", "Topic") for i in range(5)], []), {}, "m"
        )
        await s.commit()

    async with worker_db() as s:
        exp = await retrieval.expand(
            s,
            scope_set,
            [doc.id],
            fanout=retrieval.Fanout(entities_per_doc=2, neighbors_per_entity=2),
        )

    assert len(exp.entities) == 2
