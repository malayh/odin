"""Ingestion orchestration: intake, blob storage, content-hash dedup + versioning, enqueue jobs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.models import DocState, Document, Job
from odin.services import blobs, converters
from odin.worker.tasks import ingest as ingest_task


async def intake(
    session: AsyncSession, owner_id: uuid.UUID, key: str, data: bytes
) -> tuple[Document, Job | None, bool]:
    converters.format_for_key(key)
    chash = blobs.content_hash(data)
    active = await session.scalar(
        select(Document).where(
            Document.owner_user_id == owner_id,
            Document.key == key,
            Document.supersedes_id.is_(None),
        )
    )
    if active is not None and active.content_hash == chash:
        return active, None, True

    blob_uri = await blobs.put(data)
    doc_id = uuid.uuid4()
    if active is not None:
        active.supersedes_id = doc_id
        await session.flush()
    doc = Document(
        id=doc_id,
        owner_user_id=owner_id,
        key=key,
        content_hash=chash,
        blob_uri=blob_uri,
        version=active.version + 1 if active is not None else 1,
        state=DocState.pending,
    )
    session.add(doc)
    await session.flush()
    job = Job(document_id=doc.id, type="ingest")
    session.add(job)
    await session.flush()
    connection = (await (await session.connection()).get_raw_connection()).driver_connection
    await ingest_task.configure(connection=connection).defer_async(job_id=str(job.id))
    await session.commit()
    return doc, job, False
