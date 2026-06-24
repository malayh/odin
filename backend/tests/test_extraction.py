import uuid

from odin.models import Chunk, DocState, Document, ScopeType, User
from odin.services import extraction
from odin.services.extraction import Extracted, ExtractedEntity, ExtractedRelation


async def _doc_with_chunks(session, n_chunks):
    user = User(email=f"ex-{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()
    doc = Document(
        owner_user_id=user.id,
        scope_type=ScopeType.personal,
        scope_id=user.id,
        key="ex.md",
        content_hash=uuid.uuid4().hex,
        state=DocState.pending,
    )
    session.add(doc)
    await session.flush()
    for i in range(n_chunks):
        session.add(
            Chunk(
                document_id=doc.id,
                ordinal=i,
                text=f"chunk {i}",
                section_meta={"headings": []},
                char_start=0,
                char_end=1,
            )
        )
    await session.flush()
    return doc


async def test_extract_normalizes_and_dedupes(db_session, monkeypatch):
    doc = await _doc_with_chunks(db_session, 2)

    async def fake(prompt, schema, system=None):
        return Extracted(
            entities=[
                ExtractedEntity(name="Acme", type="org", confidence=0.7),
                ExtractedEntity(name="NYC", type="Place", confidence=0.5),
            ],
            relations=[
                ExtractedRelation(
                    subject="Acme", predicate="located in", object="NYC", confidence=0.6
                )
            ],
        )

    monkeypatch.setattr(extraction.llm, "complete_json", fake)
    out = await extraction.extract(db_session, doc.id)

    by_name = {e.name: e for e in out.entities}
    assert set(by_name) == {"Acme", "NYC"}
    assert by_name["Acme"].type == "Org"
    assert len(out.relations) == 1
    rel = out.relations[0]
    assert rel.predicate == "LOCATED_IN"
    assert rel.confidence == 0.6
    assert 0.0 <= by_name["Acme"].confidence <= 1.0


async def test_extract_empty_document_returns_empty(db_session, monkeypatch):
    doc = await _doc_with_chunks(db_session, 0)

    async def fake(prompt, schema, system=None):
        raise AssertionError("should not be called for a chunkless doc")

    monkeypatch.setattr(extraction.llm, "complete_json", fake)
    out = await extraction.extract(db_session, doc.id)
    assert out.entities == []
    assert out.relations == []
