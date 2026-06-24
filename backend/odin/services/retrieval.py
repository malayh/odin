"""Retrieval: scope-filtered vector recall over chunk embeddings."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.models import Chunk, DocState, Document, Embedding
from odin.services import embedding
from odin.tenancy import Scope, ScopeSet, scope_filter


@dataclass(frozen=True)
class Hit:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    ordinal: int
    text: str
    section_meta: dict[str, Any] | None
    char_start: int
    char_end: int
    scope_type: str
    scope_id: uuid.UUID
    score: float


async def search(
    session: AsyncSession,
    scope_set: ScopeSet,
    query: str,
    only: Scope | None = None,
    top_k: int = 10,
) -> list[Hit]:
    qvec = (await embedding.embed_texts([query]))[0]
    distance = Embedding.vector.cosine_distance(qvec)
    rows = (
        await session.execute(
            select(
                Document.id,
                Chunk.id,
                Chunk.ordinal,
                Chunk.text,
                Chunk.section_meta,
                Chunk.char_start,
                Chunk.char_end,
                Document.scope_type,
                Document.scope_id,
                distance.label("distance"),
            )
            .select_from(Embedding)
            .join(Chunk, Chunk.id == Embedding.chunk_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                scope_filter(scope_set, only),
                Document.supersedes_id.is_(None),
                Document.state != DocState.soft_deleted,
            )
            .order_by(distance)
            .limit(top_k)
        )
    ).all()
    return [
        Hit(
            document_id=r[0],
            chunk_id=r[1],
            ordinal=r[2],
            text=r[3],
            section_meta=r[4],
            char_start=r[5],
            char_end=r[6],
            scope_type=r[7].value,
            scope_id=r[8],
            score=1.0 - float(r[9]),
        )
        for r in rows
    ]
