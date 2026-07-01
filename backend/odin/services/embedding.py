"""Embedding provider calls (OpenAI), configured by settings.embedding_model."""

import asyncio
import uuid
from functools import lru_cache
from typing import Any

from openai import OpenAI
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.models import Chunk, Document, ObjectEmbedding

_BATCH = 128
_MAX_ATTEMPTS = 3


@lru_cache
def _client() -> Any:
    return OpenAI(api_key=get_settings().openai_api_key)


def _embed_batch(model: str, batch: list[str]) -> list[list[float]]:
    last: Exception = RuntimeError("embedding failed")
    for _ in range(_MAX_ATTEMPTS):
        try:
            resp = _client().embeddings.create(model=model, input=batch)
            return [list(d.embedding) for d in resp.data]
        except Exception as e:
            last = e
    raise last


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = get_settings().embedding_model
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        out.extend(_embed_batch(model, texts[i : i + _BATCH]))
    return out


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_chunks(session: AsyncSession, document_id: uuid.UUID) -> None:
    owner = await session.scalar(
        select(Document.owner_user_id).where(Document.id == document_id)
    )
    rows = (
        (
            await session.execute(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return
    vectors = await embed_texts([c.text for c in rows])
    for c, v in zip(rows, vectors, strict=True):
        session.add(
            ObjectEmbedding(
                object_type="chunk",
                object_id=str(c.id),
                field="text",
                owner_user_id=owner,
                vector=v,
            )
        )


async def upsert_object_embeddings(
    session: AsyncSession,
    object_type: str,
    field: str,
    owner: uuid.UUID,
    items: list[tuple[str, str]],
) -> None:
    if not items:
        return
    vectors = await embed_texts([text for _, text in items])
    for (object_id, _), vec in zip(items, vectors, strict=True):
        ins = pg_insert(ObjectEmbedding).values(
            object_type=object_type,
            object_id=object_id,
            field=field,
            owner_user_id=owner,
            vector=vec,
        )
        await session.execute(
            ins.on_conflict_do_update(
                index_elements=["object_type", "object_id", "field"],
                set_={
                    "vector": ins.excluded.vector,
                    "owner_user_id": ins.excluded.owner_user_id,
                    "updated_at": func.now(),
                },
            )
        )


async def delete_object_embeddings(
    session: AsyncSession, object_type: str, object_id: str
) -> None:
    await session.execute(
        delete(ObjectEmbedding).where(
            ObjectEmbedding.object_type == object_type,
            ObjectEmbedding.object_id == object_id,
        )
    )


async def entity_vectors(
    session: AsyncSession, owner: uuid.UUID, keys: list[str] | None = None
) -> dict[str, list[float]]:
    stmt = select(ObjectEmbedding.object_id, ObjectEmbedding.vector).where(
        ObjectEmbedding.object_type == "entity",
        ObjectEmbedding.owner_user_id == owner,
    )
    if keys is not None:
        stmt = stmt.where(ObjectEmbedding.object_id.in_(keys))
    rows = (await session.execute(stmt)).all()
    return {k: list(v) for k, v in rows}


async def nearest_entities(
    session: AsyncSession,
    owner: uuid.UUID,
    vector: list[float],
    *,
    type_prefix: str,
    top_k: int,
    exclude_key: str | None = None,
) -> list[tuple[str, float]]:
    distance = ObjectEmbedding.vector.cosine_distance(vector)
    rows = (
        await session.execute(
            select(ObjectEmbedding.object_id, distance.label("d"))
            .where(
                ObjectEmbedding.object_type == "entity",
                ObjectEmbedding.owner_user_id == owner,
                ObjectEmbedding.object_id.like(f"{type_prefix}:%"),
            )
            .order_by(distance)
            .limit(top_k + 1)
        )
    ).all()
    return [(k, float(d)) for k, d in rows if k != exclude_key][:top_k]
