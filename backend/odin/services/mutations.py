"""Append-only graph mutation log: record / explain / undo / replay graph changes."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import NotFoundError
from odin.models import GraphMutation

_ENTITY_FIELDS = (
    "key",
    "entity_key",
    "subject_key",
    "object_key",
    "canonical_key",
    "absorbed_key",
)


async def log(
    session: AsyncSession,
    *,
    actor: str,
    op: str,
    payload: dict[str, Any],
    rationale: str | None = None,
    confidence: float | None = None,
) -> uuid.UUID:
    row = GraphMutation(
        actor=actor, op=op, payload=payload, rationale=rationale, confidence=confidence
    )
    session.add(row)
    await session.flush()
    return row.id


async def explain(
    session: AsyncSession,
    *,
    entity_key: str | None = None,
    edge_id: str | None = None,
) -> Sequence[GraphMutation]:
    stmt = select(GraphMutation).order_by(GraphMutation.seq)
    if entity_key is not None:
        stmt = stmt.where(
            or_(*[GraphMutation.payload[f].astext == entity_key for f in _ENTITY_FIELDS])
        )
    if edge_id is not None:
        stmt = stmt.where(GraphMutation.payload["edge_id"].astext == edge_id)
    return (await session.execute(stmt)).scalars().all()


async def replay(session: AsyncSession, since: datetime | None = None) -> Sequence[GraphMutation]:
    stmt = select(GraphMutation).order_by(GraphMutation.seq)
    if since is not None:
        stmt = stmt.where(GraphMutation.created_at >= since)
    return (await session.execute(stmt)).scalars().all()


async def undo(session: AsyncSession, mutation_id: uuid.UUID) -> uuid.UUID:
    from odin.services import graph

    row = await session.get(GraphMutation, mutation_id)
    if row is None:
        raise NotFoundError(f"mutation not found: {mutation_id}")
    await graph.apply_inverse(session, row.op, row.payload)
    return await log(
        session,
        actor="undo",
        op=f"undo_{row.op}",
        payload={"undid": str(mutation_id), **row.payload},
    )
