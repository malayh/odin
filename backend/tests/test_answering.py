import uuid

from odin.services import answering
from odin.services.answering import _LlmAnswer
from odin.services.retrieval import Expansion, Hit
from odin.tenancy import ScopeSet


def _hit(text, doc_id=None, scope_id=None):
    return Hit(
        document_id=doc_id or uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        ordinal=0,
        text=text,
        section_meta=None,
        char_start=0,
        char_end=len(text),
        scope_type="personal",
        scope_id=scope_id or uuid.uuid4(),
        score=0.9,
    )


def _empty_expansion():
    return Expansion(entities=[], relationships=[], linked_document_ids=[])


def _fake_pipeline(monkeypatch, hits, llm_answer, calls=None):
    async def fake_search_graph(session, scope_set, query, only=None, top_k=10):
        return hits, _empty_expansion()

    async def fake_rerank(query, h):
        return h

    async def fake_llm(prompt, schema, system=None):
        if calls is not None:
            calls.append(prompt)
        return llm_answer

    monkeypatch.setattr(answering.retrieval, "search_graph", fake_search_graph)
    monkeypatch.setattr(answering.reranker, "rerank", fake_rerank)
    monkeypatch.setattr(answering.llm, "complete_json", fake_llm)


def _scope_set():
    return ScopeSet(user_id=uuid.uuid4(), roles={})


async def test_answer_grounded_with_scoped_citations(monkeypatch):
    doc = uuid.uuid4()
    scope = uuid.uuid4()
    hit = _hit("Mara founded Helios.", doc_id=doc, scope_id=scope)
    llm_answer = _LlmAnswer(
        answer="Mara founded Helios.", confident=True, used_document_ids=[str(doc)]
    )
    _fake_pipeline(monkeypatch, [hit], llm_answer)

    out = await answering.answer(None, _scope_set(), "who founded Helios?")
    assert out.confident is True
    assert out.text == "Mara founded Helios."
    assert len(out.citations) == 1
    assert out.citations[0].document_id == doc
    assert out.citations[0].scope_type == "personal"
    assert out.citations[0].scope_id == scope


async def test_answer_refuses_without_calling_llm_when_no_context(monkeypatch):
    calls: list[str] = []
    _fake_pipeline(
        monkeypatch,
        [],
        _LlmAnswer(answer="x", confident=True, used_document_ids=[]),
        calls=calls,
    )

    out = await answering.answer(None, _scope_set(), "anything?")
    assert out.confident is False
    assert "knowledge base" in out.text
    assert out.citations == []
    assert calls == []


async def test_answer_drops_ungrounded_world_knowledge(monkeypatch):
    hit = _hit("Helios builds robots.")
    llm_answer = _LlmAnswer(
        answer="The sun rises in the east.",
        confident=True,
        used_document_ids=["not-in-scope"],
    )
    _fake_pipeline(monkeypatch, [hit], llm_answer)

    out = await answering.answer(None, _scope_set(), "which way does the sun rise?")
    assert out.confident is False
    assert "knowledge base" in out.text
    assert out.citations == []


async def test_answer_keeps_only_in_scope_citations(monkeypatch):
    doc = uuid.uuid4()
    hit = _hit("fact", doc_id=doc)
    llm_answer = _LlmAnswer(
        answer="grounded",
        confident=True,
        used_document_ids=[str(uuid.uuid4()), str(doc)],
    )
    _fake_pipeline(monkeypatch, [hit], llm_answer)

    out = await answering.answer(None, _scope_set(), "q")
    assert [c.document_id for c in out.citations] == [doc]
