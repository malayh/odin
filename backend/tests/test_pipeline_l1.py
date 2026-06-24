import asyncio
import uuid

from odin.models import Chunk, DocState, Document, Job, JobState, ScopeType, User
from odin.services import blobs, embedding, llm
from odin.services.extraction import Extracted
from odin.worker import queue
from odin.worker.handlers import HANDLERS
from odin.worker.runner import _run
from sqlalchemy import func, select

SRC = b"# Title\n\nHello world, this is a body.\n\n## Section\n\nMore text lives here.\n"


async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def _fake_llm(prompt, schema, system=None):
    if schema.__name__ == "Extracted":
        return Extracted()
    return schema(same=False)


async def _seed(sm) -> dict:
    async with sm() as s:
        user = User(email=f"p-{uuid.uuid4()}@example.com")
        s.add(user)
        await s.flush()
        doc = Document(
            owner_user_id=user.id,
            scope_type=ScopeType.personal,
            scope_id=user.id,
            key="p.md",
            content_hash="h",
            blob_uri="s3://odin/h",
            version=1,
            state=DocState.pending,
        )
        s.add(doc)
        await s.flush()
        job = await queue.enqueue(s, doc.id, "ingest")
        await s.commit()
        return {"id": job.id, "document_id": doc.id, "type": "ingest", "attempts": 1}


async def _run_one(job: dict) -> None:
    pending = [job]
    stop = asyncio.Event()

    async def claim():
        if pending:
            return pending.pop()
        stop.set()
        return None

    await asyncio.wait_for(_run(claim, HANDLERS, stop, queue.complete, queue.fail), timeout=15)


async def _count_chunks(sm, document_id: uuid.UUID) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )


async def test_happy_path_chunks_and_completes(worker_db, monkeypatch):
    async def fake_get(uri: str) -> bytes:
        return SRC

    monkeypatch.setattr(blobs, "get", fake_get)
    monkeypatch.setattr(embedding, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(llm, "complete_json", _fake_llm)
    job = await _seed(worker_db)
    await _run_one(job)

    assert await _count_chunks(worker_db, job["document_id"]) >= 1
    async with worker_db() as s:
        jrow = await s.get(Job, job["id"])
        doc = await s.get(Document, job["document_id"])
        assert jrow.state is JobState.done
        assert doc.state is DocState.indexed


async def test_retry_is_idempotent(worker_db, monkeypatch):
    async def fake_get(uri: str) -> bytes:
        return SRC

    monkeypatch.setattr(blobs, "get", fake_get)
    monkeypatch.setattr(embedding, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(llm, "complete_json", _fake_llm)
    job = await _seed(worker_db)
    await _run_one(dict(job))
    n1 = await _count_chunks(worker_db, job["document_id"])
    await _run_one(dict(job))
    n2 = await _count_chunks(worker_db, job["document_id"])
    assert n1 == n2 >= 1


async def test_handler_failure_records_error(worker_db, monkeypatch):
    async def boom(uri: str) -> bytes:
        raise RuntimeError("blob exploded")

    monkeypatch.setattr(blobs, "get", boom)
    job = await _seed(worker_db)
    await _run_one(job)
    async with worker_db() as s:
        jrow = await s.get(Job, job["id"])
        assert jrow.state is JobState.pending
        assert jrow.error is not None
