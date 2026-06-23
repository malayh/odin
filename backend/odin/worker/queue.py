"""Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED): claim, complete, retry."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.db import SessionLocal
from odin.models import DocState, Document, Job, JobState


async def enqueue(session: AsyncSession, document_id: uuid.UUID, type: str) -> Job:
    job = Job(document_id=document_id, type=type)
    session.add(job)
    await session.flush()
    return job


def _as_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "type": job.type,
        "attempts": job.attempts,
    }


async def claim() -> dict[str, Any] | None:
    async with SessionLocal() as session, session.begin():
        job = await session.scalar(
            select(Job)
            .where(Job.state == JobState.pending)
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.state = JobState.running
        job.attempts += 1
        return _as_dict(job)


async def complete(job_id: uuid.UUID) -> None:
    async with SessionLocal() as session, session.begin():
        job = await session.get(Job, job_id)
        if job is not None:
            job.state = JobState.done


async def fail(job_id: uuid.UUID, error: str) -> None:
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
