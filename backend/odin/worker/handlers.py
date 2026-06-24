"""Job handlers: the ingestion pipeline stages, registered per job type."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete

from odin.config import get_settings
from odin.db import SessionLocal
from odin.errors import NotFoundError
from odin.models import Chunk, DocState, Document
from odin.services import (
    blobs,
    chunking,
    converters,
    embedding,
    extraction,
    graph,
    resolution,
)

Handler = Callable[[dict[str, Any]], Awaitable[None]]

HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return deco


@register("ingest")
async def ingest_handler(job: dict[str, Any]) -> None:
    document_id = job["document_id"]
    settings = get_settings()
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.blob_uri is None:
            raise NotFoundError(f"document not ingestable: {document_id}")
        data = await blobs.get(doc.blob_uri)
        text = converters.convert(data, doc.key)
        chunks = chunking.chunk(
            text,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
        )
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        for c in chunks:
            session.add(
                Chunk(
                    document_id=document_id,
                    ordinal=c.ordinal,
                    text=c.text,
                    section_meta=c.section_meta,
                    char_start=c.char_start,
                    char_end=c.char_end,
                )
            )
        await session.flush()
        await embedding.embed_chunks(session, document_id)

        scope_type = doc.scope_type.value
        scope_id = str(doc.scope_id)
        extracted = await extraction.extract(session, document_id)
        merges = await resolution.resolve(
            session, extracted, scope_type, scope_id, str(document_id)
        )
        await graph.delete_document_contributions(session, str(document_id))
        await graph.upsert(session, doc, extracted, merges, settings.answer_model)
        await graph.detect_and_link_contradictions(session, scope_type, scope_id)

        doc.state = DocState.indexed
        await session.commit()
