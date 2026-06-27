import uuid

from odin.models import DocState, Document, Job, User
from odin.services import blobs, embedding, graph, llm
from odin.services.extraction import Extracted, ExtractedEntity, ExtractedRelation
from odin.worker import tasks

SRC = {
    "s3://odin/a": b"# A\n\n" + b"Bob works at Acme. " * 20,
    "s3://odin/b": b"# B\n\n" + b"Bob works at Globex. " * 20,
}


async def _fake_embed_texts(texts):
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def _fake_llm(prompt, schema, system=None, model=None, max_tokens=None):
    if schema.__name__ == "Extracted":
        if "Globex" in prompt:
            return Extracted(
                entities=[
                    ExtractedEntity(name="Bob", type="Person", confidence=0.9),
                    ExtractedEntity(name="Globex", type="Org", confidence=0.9),
                ],
                relations=[
                    ExtractedRelation(
                        subject="Bob", predicate="works at", object="Globex", confidence=0.9
                    )
                ],
            )
        return Extracted(
            entities=[
                ExtractedEntity(name="Bob", type="Person", confidence=0.9),
                ExtractedEntity(name="Acme", type="Org", confidence=0.9),
            ],
            relations=[
                ExtractedRelation(
                    subject="Bob", predicate="works at", object="Acme", confidence=0.9
                )
            ],
        )
    return schema(same=False)


async def _seed(sm, uid, blob_uri):
    async with sm() as s:
        doc = Document(
            owner_user_id=uid,
            key=f"{uuid.uuid4()}.md",
            content_hash=uuid.uuid4().hex,
            blob_uri=blob_uri,
            version=1,
            state=DocState.pending,
        )
        s.add(doc)
        await s.flush()
        job = Job(document_id=doc.id, type="ingest")
        s.add(job)
        await s.commit()
        return {"id": job.id, "document_id": doc.id}


def _setup(monkeypatch):
    async def fake_get(uri):
        return SRC[uri]

    monkeypatch.setattr(blobs, "get", fake_get)
    monkeypatch.setattr(embedding, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(llm, "complete_json", _fake_llm)


async def test_pipeline_builds_scoped_provenance_graph(worker_db, monkeypatch):
    _setup(monkeypatch)
    uid = uuid.uuid4()
    async with worker_db() as s:
        s.add(User(id=uid, email=f"l3-{uid}@example.com"))
        await s.commit()

    job = await _seed(worker_db, uid, "s3://odin/a")
    await tasks.ingest(job_id=str(job["id"]))

    async with worker_db() as s:
        doc = await s.get(Document, job["document_id"])
        assert doc.state is DocState.indexed
        rels = await graph._cy(
            s,
            "MATCH (s:Entity)-[r:REL]->(o:Entity) RETURN s.key, r.predicate, o.key, "
            "r.owner, r.confidence, r.model",
            columns=("s", "p", "o", "owner", "conf", "model"),
        )
    assert ("person:bob", "WORKS_AT", "org:acme", str(uid), 0.9) == rels[0][:5]
    assert rels[0][5]


async def test_pipeline_reingest_is_idempotent(worker_db, monkeypatch):
    _setup(monkeypatch)
    uid = uuid.uuid4()
    async with worker_db() as s:
        s.add(User(id=uid, email=f"l3c-{uid}@example.com"))
        await s.commit()

    job_a = await _seed(worker_db, uid, "s3://odin/a")
    job_b = await _seed(worker_db, uid, "s3://odin/b")
    await tasks.ingest(job_id=str(job_a["id"]))
    await tasks.ingest(job_id=str(job_b["id"]))

    async def _rel_count():
        async with worker_db() as s:
            rows = await graph._cy(s, "MATCH ()-[r:REL]->() RETURN count(r)", columns=("c",))
            return rows[0][0]

    before = await _rel_count()
    await tasks.ingest(job_id=str(job_a["id"]))
    after = await _rel_count()
    assert before == after
