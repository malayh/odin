"""Embedding provider calls (OpenAI), configured by settings.embedding_model."""

import asyncio
import uuid
from functools import lru_cache
from typing import Any

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.models import Chunk, Embedding

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
        session.add(Embedding(chunk_id=c.id, vector=v))
