import asyncio
import uuid

from odin.models import Chunk, DocState, Document, Embedding, Job, JobState, ScopeType, User
from odin.services import blobs, embedding, llm
from odin.services.extraction import Extracted
from odin.worker import queue
from odin.worker.handlers import HANDLERS
from odin.worker.runner import _run
from sqlalchemy import func, select

SRC = b"# Title\n\n" + b"word " * 300


async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def _fake_llm(prompt, schema, system=None):
    if schema.__name__ == "Extracted":
        return Extracted()
    return schema(same=False)


async def _seed(sm) -> dict:
    async with sm() as s:
        user = User(email=f"l2-{uuid.uuid4()}@example.com")
        s.add(user)
        await s.flush()
        doc = Document(
            owner_user_id=user.id,
            scope_type=ScopeType.personal,
            scope_id=user.id,
            key="l2.md",
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


async def _counts(sm, document_id: uuid.UUID) -> tuple[int, int]:
    async with sm() as s:
        n_chunks = await s.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )
        n_vecs = await s.scalar(
            select(func.count())
            .select_from(Embedding)
            .join(Chunk, Chunk.id == Embedding.chunk_id)
            .where(Chunk.document_id == document_id)
        )
        return n_chunks, n_vecs


async def test_pipeline_embeds_and_indexes(worker_db, monkeypatch):
    async def fake_get(uri: str) -> bytes:
        return SRC

    monkeypatch.setattr(blobs, "get", fake_get)
    monkeypatch.setattr(embedding, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(llm, "complete_json", _fake_llm)
    job = await _seed(worker_db)
    await _run_one(job)

    n_chunks, n_vecs = await _counts(worker_db, job["document_id"])
    assert n_chunks >= 1
    assert n_vecs == n_chunks
    async with worker_db() as s:
        doc = await s.get(Document, job["document_id"])
        jrow = await s.get(Job, job["id"])
        assert doc.state is DocState.indexed
        assert jrow.state is JobState.done


async def test_reembed_replaces_vectors_cleanly(worker_db, monkeypatch):
    async def fake_get(uri: str) -> bytes:
        return SRC

    monkeypatch.setattr(blobs, "get", fake_get)
    monkeypatch.setattr(embedding, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(llm, "complete_json", _fake_llm)
    job = await _seed(worker_db)
    await _run_one(dict(job))
    c1, v1 = await _counts(worker_db, job["document_id"])
    await _run_one(dict(job))
    c2, v2 = await _counts(worker_db, job["document_id"])
    assert c1 == c2 == v1 == v2 >= 1
