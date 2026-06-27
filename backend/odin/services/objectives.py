"""Objectives: distinct AGE `Objective` nodes (full graph participants), owner-scoped."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.errors import NotFoundError
from odin.graphdb import cypher
from odin.services import mutations


async def _cy(
    session: AsyncSession,
    query: str,
    params: dict[str, Any] | None = None,
    columns: tuple[str, ...] = ("v",),
) -> list[tuple[Any, ...]]:
    return await cypher(session, get_settings().age_graph, query, params, columns=columns)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def create(
    session: AsyncSession, owner: uuid.UUID, text: str, *, dry_run: bool = False
) -> dict[str, Any]:
    if dry_run:
        return {"applied": False, "summary": f"would create objective: {text!r}"}
    oid = str(uuid.uuid4())
    await _cy(
        session,
        "CREATE (o:Objective {id:$id, text:$text, owner:$owner, origin:'user', "
        "created_at:$now})",
        {"id": oid, "text": text, "owner": str(owner), "now": _now()},
    )
    await mutations.log(
        session,
        actor="user",
        op="objective_add",
        payload={"id": oid, "owner": str(owner), "text": text},
    )
    return {"applied": True, "summary": f"created objective {oid}", "id": oid}


async def infer(
    session: AsyncSession,
    owner: uuid.UUID,
    source_doc_id: str,
    text: str,
    confidence: float,
) -> str:
    norm = " ".join(text.split()).lower()
    oid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{owner}|{source_doc_id}|{norm}"))
    await _cy(
        session,
        "MERGE (o:Objective {id:$id}) "
        "SET o.text=$text, o.owner=$owner, o.origin='inferred', o.trust='proposed', "
        "o.source_doc_id=$sdid, o.confidence=$confidence, "
        "o.created_at=coalesce(o.created_at, $now)",
        {
            "id": oid,
            "text": text,
            "owner": str(owner),
            "sdid": source_doc_id,
            "confidence": confidence,
            "now": _now(),
        },
    )
    await mutations.log(
        session,
        actor="extractor",
        op="objective_infer",
        payload={"id": oid, "owner": str(owner), "text": text, "source_doc_id": source_doc_id},
        confidence=confidence,
    )
    return oid


async def list_for_owner(session: AsyncSession, owner: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _cy(
        session,
        "MATCH (o:Objective) WHERE o.owner=$owner "
        "RETURN o.id, o.text, o.created_at ORDER BY o.created_at",
        {"owner": str(owner)},
        columns=("id", "text", "created_at"),
    )
    return [{"id": r[0], "text": r[1], "created_at": r[2]} for r in rows]


async def drop(
    session: AsyncSession, owner: uuid.UUID, objective_id: str, *, dry_run: bool = False
) -> dict[str, Any]:
    found = await _cy(
        session,
        "MATCH (o:Objective {id:$id}) WHERE o.owner=$owner RETURN o.id",
        {"id": objective_id, "owner": str(owner)},
        columns=("id",),
    )
    if not found:
        raise NotFoundError(f"objective not found: {objective_id}")
    if dry_run:
        return {"applied": False, "summary": f"would drop objective {objective_id}"}
    await _cy(
        session,
        "MATCH (o:Objective {id:$id}) WHERE o.owner=$owner DETACH DELETE o",
        {"id": objective_id, "owner": str(owner)},
    )
    await mutations.log(
        session,
        actor="user",
        op="objective_drop",
        payload={"id": objective_id, "owner": str(owner)},
    )
    return {"applied": True, "summary": f"dropped objective {objective_id}", "id": objective_id}
