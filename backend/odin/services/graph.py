"""Knowledge graph access over Apache AGE: nodes/edges carrying scope + provenance + confidence."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.graphdb import cypher
from odin.models import Document
from odin.services import mutations, ontology
from odin.tenancy import ScopeSet


async def _cy(
    session: AsyncSession,
    query: str,
    params: dict[str, Any] | None = None,
    columns: tuple[str, ...] = ("v",),
) -> list[tuple[Any, ...]]:
    return await cypher(session, get_settings().age_graph, query, params, columns=columns)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scope_clause(scope_set: ScopeSet, var: str) -> tuple[str, dict[str, Any]]:
    parts = [f"({var}.scope_type = 'personal' AND {var}.scope_id = $sc_uid)"]
    params: dict[str, Any] = {"sc_uid": str(scope_set.user_id)}
    if scope_set.org_ids:
        parts.append(f"({var}.scope_type = 'org' AND {var}.scope_id IN $sc_orgs)")
        params["sc_orgs"] = [str(o) for o in scope_set.org_ids]
    return "(" + " OR ".join(parts) + ")", params


async def upsert_document(session: AsyncSession, doc: Document) -> None:
    await _cy(
        session,
        "MERGE (d:Document {doc_id:$doc_id}) "
        "SET d.scope_type=$scope_type, d.scope_id=$scope_id, "
        "d.created_at=coalesce(d.created_at, $now)",
        {
            "doc_id": str(doc.id),
            "scope_type": doc.scope_type.value,
            "scope_id": str(doc.scope_id),
            "now": _now(),
        },
    )


async def upsert_entity(session: AsyncSession, key: str, name: str, type_: str) -> None:
    await _cy(
        session,
        "MERGE (e:Entity {key:$key}) "
        "SET e.name=$name, e.type=$type, e.created_at=coalesce(e.created_at, $now)",
        {"key": key, "name": name, "type": type_, "now": _now()},
    )


async def add_mention(
    session: AsyncSession,
    doc: Document,
    entity_key: str,
    alias: str,
    origin: str,
    confidence: float,
    model: str,
) -> None:
    await _cy(
        session,
        "MATCH (d:Document {doc_id:$doc_id}), (e:Entity {key:$key}) "
        "CREATE (d)-[:MENTIONS {scope_type:$scope_type, scope_id:$scope_id, "
        "source_doc_id:$doc_id, alias:$alias, origin:$origin, confidence:$confidence, "
        "method:'extract', model:$model, created_at:$now}]->(e)",
        {
            "doc_id": str(doc.id),
            "key": entity_key,
            "scope_type": doc.scope_type.value,
            "scope_id": str(doc.scope_id),
            "alias": alias,
            "origin": origin,
            "confidence": confidence,
            "model": model,
            "now": _now(),
        },
    )


async def add_relationship(
    session: AsyncSession,
    doc: Document,
    subject_key: str,
    predicate: str,
    object_key: str,
    origin: str,
    confidence: float,
    model: str,
) -> None:
    await _cy(
        session,
        "MATCH (s:Entity {key:$subj}), (o:Entity {key:$obj}) "
        "CREATE (s)-[:REL {predicate:$predicate, scope_type:$scope_type, scope_id:$scope_id, "
        "source_doc_id:$doc_id, origin:$origin, confidence:$confidence, method:'extract', "
        "model:$model, created_at:$now}]->(o)",
        {
            "subj": subject_key,
            "obj": object_key,
            "predicate": predicate,
            "scope_type": doc.scope_type.value,
            "scope_id": str(doc.scope_id),
            "doc_id": str(doc.id),
            "origin": origin,
            "confidence": confidence,
            "model": model,
            "now": _now(),
        },
    )


async def add_contradiction(
    session: AsyncSession,
    scope_type: str,
    scope_id: str,
    subject_key: str,
    predicate: str,
    object_a: str,
    object_b: str,
    source_doc_ids: list[str],
) -> None:
    await _cy(
        session,
        "MATCH (a:Entity {key:$a}), (b:Entity {key:$b}) "
        "CREATE (a)-[:CONTRADICTS {subject_key:$subj, predicate:$predicate, "
        "scope_type:$scope_type, scope_id:$scope_id, source_doc_ids:$sdi, created_at:$now}]->(b)",
        {
            "a": object_a,
            "b": object_b,
            "subj": subject_key,
            "predicate": predicate,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "sdi": source_doc_ids,
            "now": _now(),
        },
    )


async def delete_document_contributions(session: AsyncSession, doc_id: str) -> None:
    await _cy(
        session,
        "MATCH (d:Document {doc_id:$doc_id})-[m:MENTIONS]->() DELETE m",
        {"doc_id": doc_id},
    )
    await _cy(
        session, "MATCH ()-[r:REL]->() WHERE r.source_doc_id=$doc_id DELETE r", {"doc_id": doc_id}
    )
    await _cy(
        session,
        "MATCH ()-[c:CONTRADICTS]->() WHERE $doc_id IN c.source_doc_ids DELETE c",
        {"doc_id": doc_id},
    )
    await _cy(session, "MATCH (d:Document {doc_id:$doc_id}) DETACH DELETE d", {"doc_id": doc_id})


async def upsert(
    session: AsyncSession,
    doc: Document,
    extracted: Any,
    merges: dict[str, tuple[str, str, str]],
    model: str,
) -> None:
    await upsert_document(session, doc)
    doc_id = str(doc.id)
    name_to_key: dict[str, str] = {}
    for ent in extracted.entities:
        raw_key = ontology.entity_key(ent.name, ent.type)
        if raw_key in merges:
            key, name, type_ = merges[raw_key]
        else:
            key, name = raw_key, ent.name
            type_, _ = ontology.normalize_type(ent.type)
        await upsert_entity(session, key, name, type_)
        await mutations.log(
            session,
            actor="extractor",
            op="entity_create",
            payload={"key": key, "name": name, "type": type_},
            confidence=ent.confidence,
        )
        await add_mention(session, doc, key, ent.name, "extracted", ent.confidence, model)
        await mutations.log(
            session,
            actor="extractor",
            op="mention_add",
            payload={"entity_key": key, "alias": ent.name, "source_doc_id": doc_id},
            confidence=ent.confidence,
        )
        name_to_key[ent.name] = key
    for rel in extracted.relations:
        subj = name_to_key.get(rel.subject)
        obj = name_to_key.get(rel.object)
        if subj is None or obj is None:
            continue
        predicate, _ = ontology.normalize_predicate(rel.predicate)
        await add_relationship(
            session, doc, subj, predicate, obj, "extracted", rel.confidence, model
        )
        await mutations.log(
            session,
            actor="extractor",
            op="rel_add",
            payload={
                "subject_key": subj,
                "object_key": obj,
                "predicate": predicate,
                "source_doc_id": doc_id,
            },
            confidence=rel.confidence,
        )


async def detect_and_link_contradictions(
    session: AsyncSession, scope_type: str, scope_id: str
) -> int:
    rows = await _cy(
        session,
        "MATCH (s:Entity)-[r:REL]->(o:Entity) "
        "WHERE r.scope_type=$scope_type AND r.scope_id=$scope_id "
        "RETURN s.key, r.predicate, o.key, r.source_doc_id",
        {"scope_type": scope_type, "scope_id": scope_id},
        columns=("subject_key", "predicate", "object_key", "source_doc_id"),
    )
    groups: dict[tuple[str, str], dict[str, str]] = {}
    for subj, pred, obj, sdi in rows:
        groups.setdefault((subj, pred), {}).setdefault(obj, sdi)
    linked = 0
    for (subj, pred), objs in groups.items():
        if len(objs) < 2:
            continue
        keys = sorted(objs)
        first = keys[0]
        for other in keys[1:]:
            await add_contradiction(
                session,
                scope_type,
                scope_id,
                subj,
                pred,
                first,
                other,
                [objs[first], objs[other]],
            )
            linked += 1
    return linked


async def read_entity(
    session: AsyncSession, scope_set: ScopeSet, key: str
) -> dict[str, Any] | None:
    node = await _cy(
        session,
        "MATCH (e:Entity {key:$key}) RETURN e.name, e.type",
        {"key": key},
        columns=("name", "type"),
    )
    if not node:
        return None
    name, type_ = node[0]
    mclause, mparams = _scope_clause(scope_set, "m")
    mparams["key"] = key
    aliases = await _cy(
        session,
        f"MATCH (:Document)-[m:MENTIONS]->(e:Entity {{key:$key}}) WHERE {mclause} "
        "RETURN DISTINCT m.alias",
        mparams,
        columns=("alias",),
    )
    rclause, rparams = _scope_clause(scope_set, "r")
    rparams["key"] = key
    rels = await _cy(
        session,
        f"MATCH (e:Entity {{key:$key}})-[r:REL]->(o:Entity) WHERE {rclause} "
        "RETURN r.predicate, o.key, r.source_doc_id",
        rparams,
        columns=("predicate", "object_key", "source_doc_id"),
    )
    return {
        "key": key,
        "name": name,
        "type": type_,
        "aliases": sorted(a[0] for a in aliases),
        "relationships": [
            {"predicate": r[0], "object_key": r[1], "source_doc_id": r[2]} for r in rels
        ],
    }


async def apply_inverse(session: AsyncSession, op: str, payload: dict[str, Any]) -> None:
    if op != "merge":
        raise NotImplementedError(f"undo not supported for op: {op}")
    await upsert_entity(
        session, payload["absorbed_key"], payload["absorbed_name"], payload["absorbed_type"]
    )
    await _cy(
        session,
        "MATCH (:Document {doc_id:$doc_id})-[m:MENTIONS {alias:$alias}]->"
        "(:Entity {key:$canonical}) DELETE m",
        {
            "doc_id": payload["source_doc_id"],
            "alias": payload["alias"],
            "canonical": payload["canonical_key"],
        },
    )
    await _cy(
        session,
        "MATCH (d:Document {doc_id:$doc_id}), (b:Entity {key:$absorbed}) "
        "CREATE (d)-[:MENTIONS {scope_type:$scope_type, scope_id:$scope_id, "
        "source_doc_id:$doc_id, alias:$alias, origin:'extracted', "
        "confidence:$confidence, method:'extract', model:$model, created_at:$now}]->(b)",
        {
            "doc_id": payload["source_doc_id"],
            "absorbed": payload["absorbed_key"],
            "scope_type": payload["scope_type"],
            "scope_id": payload["scope_id"],
            "alias": payload["alias"],
            "confidence": payload.get("confidence"),
            "model": payload.get("model", ""),
            "now": _now(),
        },
    )
