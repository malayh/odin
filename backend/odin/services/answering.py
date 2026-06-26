"""RAG ask: retrieve, rerank, assemble context, generate a cited answer."""

import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.services import llm, reranker, retrieval

_REFUSAL = "I don't know — that is not in your knowledge base."

_SYSTEM = (
    "You answer strictly from the provided context, drawn from the user's knowledge base. "
    "Use only that context; never use outside or world knowledge. "
    "Cite the document ids you relied on in used_document_ids. "
    "If the context does not contain the answer, say it is not in the knowledge base "
    "and set confident to false."
)


@dataclass(frozen=True)
class Citation:
    document_id: uuid.UUID


@dataclass(frozen=True)
class Answer:
    text: str
    confident: bool
    citations: list[Citation]


class _LlmAnswer(BaseModel):
    answer: str
    confident: bool
    used_document_ids: list[str]


def _assemble(
    hits: list[retrieval.Hit], expansion: retrieval.Expansion, budget: int
) -> tuple[str, set[str]]:
    blocks: list[str] = []
    allow: set[str] = set()
    used = 0
    for h in hits:
        block = f"[doc {h.document_id}]\n{h.text}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
        allow.add(str(h.document_id))
    context = "\n\n".join(blocks)
    facts = [f"{r.subject_key} {r.predicate} {r.object_key}" for r in expansion.relationships]
    if facts:
        context += "\n\nKnown facts:\n" + "\n".join(facts)
    return context, allow


def _prompt(question: str, context: str, history: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    if history:
        parts.append("Earlier in this conversation:")
        parts += [f"{turn['role']}: {turn['content']}" for turn in history]
        parts.append("")
    parts += [f"Question: {question}", "", "Context:", context]
    return "\n".join(parts)


async def answer(
    session: AsyncSession,
    owner: uuid.UUID,
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
) -> Answer:
    settings = get_settings()
    hits, expansion = await retrieval.search_graph(
        session, owner, question, settings.ask_top_k
    )
    ranked = await reranker.rerank(question, hits)
    context, allow = _assemble(
        ranked[: settings.ask_context_chunks], expansion, settings.answer_context_max_chars
    )
    if not context:
        return Answer(text=_REFUSAL, confident=False, citations=[])
    result = await llm.complete_json(
        _prompt(question, context, history), _LlmAnswer, system=_SYSTEM
    )
    citations = [
        Citation(document_id=uuid.UUID(doc_id))
        for doc_id in dict.fromkeys(result.used_document_ids)
        if doc_id in allow
    ]
    if not citations:
        return Answer(text=_REFUSAL, confident=False, citations=[])
    return Answer(text=result.answer, confident=result.confident, citations=citations)
