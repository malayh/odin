import uuid

from odin.services import reranker
from odin.services.reranker import _Rank, _Ranking
from odin.services.retrieval import Hit


def _hit(text):
    return Hit(
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        ordinal=0,
        text=text,
        section_meta=None,
        char_start=0,
        char_end=len(text),
        score=0.5,
    )


async def test_rerank_reorders_by_score(monkeypatch):
    hits = [_hit("a"), _hit("b"), _hit("c")]

    async def fake(prompt, schema, system=None):
        return _Ranking(
            rankings=[
                _Rank(index=2, score=0.9),
                _Rank(index=0, score=0.5),
                _Rank(index=1, score=0.1),
            ]
        )

    monkeypatch.setattr(reranker.llm, "complete_json", fake)
    out = await reranker.rerank("q", hits)
    assert [h.text for h in out] == ["c", "a", "b"]


async def test_rerank_falls_back_to_input_order_on_error(monkeypatch):
    hits = [_hit("a"), _hit("b"), _hit("c")]

    async def boom(prompt, schema, system=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(reranker.llm, "complete_json", boom)
    out = await reranker.rerank("q", hits)
    assert [h.text for h in out] == ["a", "b", "c"]


async def test_rerank_never_adds_or_drops_hits(monkeypatch):
    hits = [_hit("a"), _hit("b"), _hit("c")]

    async def partial(prompt, schema, system=None):
        return _Ranking(rankings=[_Rank(index=1, score=0.9)])

    monkeypatch.setattr(reranker.llm, "complete_json", partial)
    out = await reranker.rerank("q", hits)
    assert {h.text for h in out} == {"a", "b", "c"}
    assert out[0].text == "b"
    assert [h.text for h in out[1:]] == ["a", "c"]
