"""Knowledge graph access over Apache AGE: nodes/edges carrying owner + provenance + confidence."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.graphdb import cypher
from odin.models import Document, GraphMutation
from odin.services import mutations, ontology


async def _cy(
    session: AsyncSession,
    query: str,
    params: dict[str, Any] | None = None,
    columns: tuple[str, ...] = ("v",),
) -> list[tuple[Any, ...]]:
    return await cypher(session, get_settings().age_graph, query, params, columns=columns)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _owner_clause(owner: uuid.UUID, var: str) -> tuple[str, dict[str, Any]]:
    return f"({var}.owner = $sc_uid)", {"sc_uid": str(owner)}


async def upsert_document(session: AsyncSession, doc: Document) -> None:
    await _cy(
        session,
        "MERGE (d:Document {doc_id:$doc_id}) "
        "SET d.owner=$owner, d.created_at=coalesce(d.created_at, $now)",
        {"doc_id": str(doc.id), "owner": str(doc.owner_user_id), "now": _now()},
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
        "CREATE (d)-[:MENTIONS {owner:$owner, "
        "source_doc_id:$doc_id, alias:$alias, origin:$origin, confidence:$confidence, "
        "method:'extract', model:$model, created_at:$now}]->(e)",
        {
            "doc_id": str(doc.id),
            "key": entity_key,
            "owner": str(doc.owner_user_id),
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
        "CREATE (s)-[:REL {predicate:$predicate, owner:$owner, "
        "source_doc_id:$doc_id, origin:$origin, confidence:$confidence, method:'extract', "
        "model:$model, created_at:$now}]->(o)",
        {
            "subj": subject_key,
            "obj": object_key,
            "predicate": predicate,
            "owner": str(doc.owner_user_id),
            "doc_id": str(doc.id),
            "origin": origin,
            "confidence": confidence,
            "model": model,
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


async def list_owner_entities(
    session: AsyncSession, owner: uuid.UUID
) -> list[tuple[str, str, str]]:
    rows = await _cy(
        session,
        "MATCH (:Document)-[m:MENTIONS]->(e:Entity) "
        "WHERE m.owner=$owner "
        "RETURN DISTINCT e.key, e.name, e.type",
        {"owner": str(owner)},
        columns=("key", "name", "type"),
    )
    return [(r[0], r[1], r[2]) for r in rows]


async def owner_entity_facts(
    session: AsyncSession, owner: uuid.UUID, keys: list[str]
) -> list[tuple[str, str, str]]:
    if not keys:
        return []
    rows = await _cy(
        session,
        "MATCH (e:Entity)-[r:REL]->(o:Entity) "
        "WHERE r.owner=$owner AND e.key IN $keys "
        "RETURN e.key, r.predicate, o.name",
        {"owner": str(owner), "keys": keys},
        columns=("key", "predicate", "object"),
    )
    return [(r[0], r[1], r[2]) for r in rows]


async def mentioned_entities(
    session: AsyncSession, owner: uuid.UUID, doc_ids: list[str]
) -> list[tuple[str, str, str, str, float]]:
    clause, params = _owner_clause(owner, "m")
    params["doc_ids"] = doc_ids
    rows = await _cy(
        session,
        "MATCH (d:Document)-[m:MENTIONS]->(e:Entity) "
        f"WHERE d.doc_id IN $doc_ids AND {clause} "
        "RETURN d.doc_id, e.key, e.name, e.type, m.confidence "
        "ORDER BY d.doc_id, m.confidence DESC, e.key",
        params,
        columns=("doc_id", "key", "name", "type", "confidence"),
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


async def entity_neighbors(
    session: AsyncSession, owner: uuid.UUID, keys: list[str]
) -> list[tuple[str, str, str, str, float]]:
    clause, params = _owner_clause(owner, "r")
    params["keys"] = keys
    rows = await _cy(
        session,
        "MATCH (s:Entity)-[r:REL]->(o:Entity) "
        f"WHERE s.key IN $keys AND {clause} "
        "RETURN s.key, r.predicate, o.key, r.source_doc_id, r.confidence "
        "ORDER BY s.key, r.confidence DESC, o.key",
        params,
        columns=("subject_key", "predicate", "object_key", "source_doc_id", "confidence"),
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


async def docs_for_entities(
    session: AsyncSession, owner: uuid.UUID, keys: list[str]
) -> list[tuple[str, str]]:
    clause, params = _owner_clause(owner, "m")
    params["keys"] = keys
    rows = await _cy(
        session,
        "MATCH (d:Document)-[m:MENTIONS]->(e:Entity) "
        f"WHERE e.key IN $keys AND {clause} "
        "RETURN DISTINCT e.key, d.doc_id",
        params,
        columns=("key", "doc_id"),
    )
    return [(r[0], r[1]) for r in rows]


async def read_entity(
    session: AsyncSession, owner: uuid.UUID, key: str
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
    mclause, mparams = _owner_clause(owner, "m")
    mparams["key"] = key
    aliases = await _cy(
        session,
        f"MATCH (:Document)-[m:MENTIONS]->(e:Entity {{key:$key}}) WHERE {mclause} "
        "RETURN DISTINCT m.alias",
        mparams,
        columns=("alias",),
    )
    rclause, rparams = _owner_clause(owner, "r")
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


async def find_entities(
    session: AsyncSession, owner: uuid.UUID, q: str
) -> list[tuple[str, str, str]]:
    clause, params = _owner_clause(owner, "m")
    rows = await _cy(
        session,
        "MATCH (:Document)-[m:MENTIONS]->(e:Entity) "
        f"WHERE {clause} "
        "RETURN DISTINCT e.key, e.name, e.type, m.alias",
        params,
        columns=("key", "name", "type", "alias"),
    )
    needle = q.lower()
    matched: dict[str, tuple[str, str, str]] = {}
    for key, name, type_, alias in rows:
        if needle in name.lower() or needle in (alias or "").lower():
            matched.setdefault(key, (key, name, type_))
    return sorted(matched.values())


async def entity_history(
    session: AsyncSession, owner: uuid.UUID, key: str
) -> list[GraphMutation]:
    rows = await mutations.explain(session, entity_key=key)
    doc_ids = {
        p["source_doc_id"]
        for r in rows
        if "owner" not in (p := r.payload) and "source_doc_id" in p
    }
    doc_owners: dict[str, uuid.UUID] = {}
    if doc_ids:
        result = await session.execute(
            select(Document.id, Document.owner_user_id).where(
                Document.id.in_({uuid.UUID(d) for d in doc_ids})
            )
        )
        doc_owners = {str(did): oid for did, oid in result}
    visible: list[GraphMutation] = []
    for r in rows:
        p = r.payload
        if "owner" in p:
            if p["owner"] == str(owner):
                visible.append(r)
        elif "source_doc_id" in p:
            if doc_owners.get(p["source_doc_id"]) == owner:
                visible.append(r)
        else:
            visible.append(r)
    return visible


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
        "CREATE (d)-[:MENTIONS {owner:$owner, "
        "source_doc_id:$doc_id, alias:$alias, origin:'extracted', "
        "confidence:$confidence, method:'extract', model:$model, created_at:$now}]->(b)",
        {
            "doc_id": payload["source_doc_id"],
            "absorbed": payload["absorbed_key"],
            "owner": payload["owner"],
            "alias": payload["alias"],
            "confidence": payload.get("confidence"),
            "model": payload.get("model", ""),
            "now": _now(),
        },
    )


async def merge_nodes(
    session: AsyncSession,
    canonical_key: str,
    canonical_name: str,
    canonical_type: str,
    absorbed_key: str,
) -> None:
    if absorbed_key == canonical_key:
        return
    await upsert_entity(session, canonical_key, canonical_name, canonical_type)
    mentions = await _cy(
        session,
        "MATCH (d:Document)-[m:MENTIONS]->(:Entity {key:$absorbed}) "
        "RETURN d.doc_id, m.owner, m.source_doc_id, m.alias, m.origin, "
        "m.confidence, m.method, m.model, m.created_at",
        {"absorbed": absorbed_key},
        columns=(
            "doc_id", "owner", "source_doc_id", "alias", "origin",
            "confidence", "method", "model", "created_at",
        ),
    )
    for d_id, owner, sdid, alias, origin, conf, method, model, created in mentions:
        await _cy(
            session,
            "MATCH (d:Document {doc_id:$doc_id}), (c:Entity {key:$canonical}) "
            "CREATE (d)-[:MENTIONS {owner:$owner, source_doc_id:$sdid, "
            "alias:$alias, origin:$origin, confidence:$conf, method:$method, model:$model, "
            "created_at:$created}]->(c)",
            {
                "doc_id": d_id, "canonical": canonical_key, "owner": owner, "sdid": sdid,
                "alias": alias, "origin": origin, "conf": conf, "method": method, "model": model,
                "created": created,
            },
        )
    outgoing = await _cy(
        session,
        "MATCH (:Entity {key:$absorbed})-[r:REL]->(o:Entity) "
        "WHERE o.key <> $absorbed AND o.key <> $canonical "
        "RETURN o.key, r.predicate, r.owner, r.source_doc_id, r.origin, "
        "r.confidence, r.method, r.model, r.created_at",
        {"absorbed": absorbed_key, "canonical": canonical_key},
        columns=(
            "other", "predicate", "owner", "source_doc_id", "origin",
            "confidence", "method", "model", "created_at",
        ),
    )
    incoming = await _cy(
        session,
        "MATCH (s:Entity)-[r:REL]->(:Entity {key:$absorbed}) "
        "WHERE s.key <> $absorbed AND s.key <> $canonical "
        "RETURN s.key, r.predicate, r.owner, r.source_doc_id, r.origin, "
        "r.confidence, r.method, r.model, r.created_at",
        {"absorbed": absorbed_key, "canonical": canonical_key},
        columns=(
            "other", "predicate", "owner", "source_doc_id", "origin",
            "confidence", "method", "model", "created_at",
        ),
    )
    for direction, rows in (("out", outgoing), ("in", incoming)):
        pattern = (
            "MATCH (c:Entity {key:$canonical}), (e:Entity {key:$other}) CREATE (c)-[:REL "
            if direction == "out"
            else "MATCH (c:Entity {key:$canonical}), (e:Entity {key:$other}) CREATE (e)-[:REL "
        )
        for other, pred, owner, sdid, origin, conf, method, model, created in rows:
            await _cy(
                session,
                pattern
                + "{predicate:$predicate, owner:$owner, source_doc_id:$sdid, "
                "origin:$origin, confidence:$conf, method:$method, model:$model, "
                "created_at:$created}]->" + ("(e)" if direction == "out" else "(c)"),
                {
                    "canonical": canonical_key, "other": other, "predicate": pred, "owner": owner,
                    "sdid": sdid, "origin": origin, "conf": conf, "method": method,
                    "model": model, "created": created,
                },
            )
    await _cy(
        session,
        "MATCH (a:Entity {key:$absorbed}) DETACH DELETE a",
        {"absorbed": absorbed_key},
    )
