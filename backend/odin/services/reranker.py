"""Hosted reranker: re-score retrieved candidates before context assembly."""

from pydantic import BaseModel

from odin.services import llm
from odin.services.retrieval import Hit

_SYSTEM = (
    "You re-rank retrieved passages by how well each answers the question. "
    "Return a relevance score in [0, 1] for every candidate index. "
    "Judge whether the passage actually contains the answer, not mere topical overlap."
)


class _Rank(BaseModel):
    index: int
    score: float


class _Ranking(BaseModel):
    rankings: list[_Rank]


def _prompt(query: str, hits: list[Hit]) -> str:
    lines = [f"Question: {query}", "", "Candidates:"]
    for i, h in enumerate(hits):
        lines.append(f"[{i}] {h.text}")
    return "\n".join(lines)


async def rerank(query: str, hits: list[Hit]) -> list[Hit]:
    if len(hits) <= 1:
        return hits
    try:
        result = await llm.complete_json(_prompt(query, hits), _Ranking, system=_SYSTEM)
    except Exception:
        return hits
    scores = {r.index: r.score for r in result.rankings if 0 <= r.index < len(hits)}
    order = sorted(range(len(hits)), key=lambda i: (i not in scores, -scores.get(i, 0.0), i))
    return [hits[i] for i in order]
