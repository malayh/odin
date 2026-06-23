import asyncio
import uuid

from odin.models import DocState, Document, Job, JobState, ScopeType, User
from odin.worker import queue


async def _make_doc(sm) -> uuid.UUID:
    async with sm() as s:
        user = User(email=f"q-{uuid.uuid4()}@example.com")
        s.add(user)
        await s.flush()
        doc = Document(
            owner_user_id=user.id,
            scope_type=ScopeType.personal,
            scope_id=user.id,
            key="q.md",
            content_hash="h",
            version=1,
            state=DocState.pending,
        )
        s.add(doc)
        await s.commit()
        return doc.id


async def _enqueue(sm, doc_id: uuid.UUID) -> uuid.UUID:
    async with sm() as s:
        job = await queue.enqueue(s, doc_id, "ingest")
        await s.commit()
        return job.id


async def test_claim_marks_running_and_excludes_repeat(worker_db):
    await _enqueue(worker_db, await _make_doc(worker_db))
    first = await queue.claim()
    assert first is not None
    assert first["type"] == "ingest"
    assert await queue.claim() is None


async def test_concurrent_claims_never_collide(worker_db):
    await _enqueue(worker_db, await _make_doc(worker_db))
    await _enqueue(worker_db, await _make_doc(worker_db))
    a, b = await asyncio.gather(queue.claim(), queue.claim())
    ids = {j["id"] for j in (a, b) if j is not None}
    assert len(ids) == 2


async def test_complete_sets_done(worker_db):
    job_id = await _enqueue(worker_db, await _make_doc(worker_db))
    await queue.claim()
    await queue.complete(job_id)
    async with worker_db() as s:
        assert (await s.get(Job, job_id)).state is JobState.done


async def test_fail_retries_then_terminal_marks_document(worker_db):
    doc_id = await _make_doc(worker_db)
    job_id = await _enqueue(worker_db, doc_id)

    async with worker_db() as s:
        (await s.get(Job, job_id)).attempts = 1
        await s.commit()
    await queue.fail(job_id, "boom")
    async with worker_db() as s:
        assert (await s.get(Job, job_id)).state is JobState.pending

    async with worker_db() as s:
        (await s.get(Job, job_id)).attempts = 5
        await s.commit()
    await queue.fail(job_id, "boom")
    async with worker_db() as s:
        job = await s.get(Job, job_id)
        doc = await s.get(Document, doc_id)
        assert job.state is JobState.failed
        assert job.error == "boom"
        assert doc.state is DocState.failed
