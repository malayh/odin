"""Worker tasks: the ingest pipeline and the consolidate/dream sleep-cycle runs."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from odin.config import get_settings
from odin.db import SessionLocal
from odin.errors import NotFoundError
from odin.models import Chunk, DocState, Document, Job, JobState, SleepRun, SleepState
from odin.services import (
    blobs,
    chunking,
    converters,
    embedding,
    extraction,
    graph,
    resolution,
)
from odin.worker.app import app


@app.task(name="ingest", retry=get_settings().worker_max_attempts - 1)
async def ingest(job_id: str) -> None:
    job_uuid = uuid.UUID(job_id)
    document_id = await _begin(job_uuid)
    if document_id is None:
        return
    try:
        await _pipeline(document_id)
        await _finish(job_uuid)
    except Exception as e:
        await _fail(job_uuid, repr(e))
        raise


async def _begin(job_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session, session.begin():
        job = await session.get(Job, job_id)
        if job is None:
            return None
        job.attempts += 1
        job.state = JobState.running
        return job.document_id


async def _finish(job_id: uuid.UUID) -> None:
    async with SessionLocal() as session, session.begin():
        job = await session.get(Job, job_id)
        if job is not None:
            job.state = JobState.done


async def _fail(job_id: uuid.UUID, error: str) -> None:
    async with SessionLocal() as session, session.begin():
        job = await session.get(Job, job_id)
        if job is None:
            return
        job.error = error
        if job.attempts >= get_settings().worker_max_attempts:
            job.state = JobState.failed
            doc = await session.get(Document, job.document_id)
            if doc is not None:
                doc.state = DocState.failed
        else:
            job.state = JobState.pending


async def _pipeline(document_id: uuid.UUID) -> None:
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

        extracted = await extraction.extract(session, document_id)
        merges = await resolution.resolve(
            session, extracted, doc.owner_user_id, str(document_id)
        )
        await graph.delete_document_contributions(session, str(document_id))
        await graph.upsert(session, doc, extracted, merges, settings.answer_model)

        doc.state = DocState.indexed
        await session.commit()


@app.task(name="consolidate")
async def consolidate(run_id: str, full: bool = False) -> None:
    await _run_sleep(uuid.UUID(run_id), lambda owner: _consolidate_body(owner, full))


@app.task(name="dream")
async def dream(run_id: str) -> None:
    await _run_sleep(uuid.UUID(run_id), _dream_body)


async def _run_sleep(
    run_id: uuid.UUID, body: Callable[[uuid.UUID], Awaitable[dict[str, Any]]]
) -> None:
    owner = await _sleep_begin(run_id)
    if owner is None:
        return
    try:
        stats = await body(owner)
        await _sleep_finish(run_id, stats)
    except Exception as e:
        await _sleep_fail(run_id, repr(e))
        raise


async def _consolidate_body(owner: uuid.UUID, full: bool) -> dict[str, Any]:
    async with SessionLocal() as session:
        since = None
        if not full:
            since = await session.scalar(
                select(SleepRun.finished_at)
                .where(
                    SleepRun.owner_user_id == owner,
                    SleepRun.type == "consolidate",
                    SleepRun.state == SleepState.succeeded,
                )
                .order_by(SleepRun.finished_at.desc())
                .limit(1)
            )
        merged = await resolution.deep_consolidate(session, owner, since=since)
        await session.commit()
        return {"merges": merged, "mode": "full" if since is None else "incremental"}


async def _dream_body(owner: uuid.UUID) -> dict[str, Any]:
    return {"note": "REM not yet implemented"}


async def _sleep_begin(run_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session, session.begin():
        run = await session.get(SleepRun, run_id)
        if run is None:
            return None
        run.state = SleepState.running
        run.started_at = datetime.now(UTC)
        return run.owner_user_id


async def _sleep_finish(run_id: uuid.UUID, stats: dict[str, Any]) -> None:
    async with SessionLocal() as session, session.begin():
        run = await session.get(SleepRun, run_id)
        if run is not None:
            run.state = SleepState.succeeded
            run.finished_at = datetime.now(UTC)
            run.stats = stats


async def _sleep_fail(run_id: uuid.UUID, error: str) -> None:
    async with SessionLocal() as session, session.begin():
        run = await session.get(SleepRun, run_id)
        if run is not None:
            run.state = SleepState.failed
            run.finished_at = datetime.now(UTC)
            run.error = error
