"""Retrieval: owner-filtered vector recall over chunk embeddings."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.models import Chunk, DocState, Document, Embedding
from odin.services import embedding, graph
from odin.tenancy import owner_filter


@dataclass(frozen=True)
class Hit:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    ordinal: int
    text: str
    section_meta: dict[str, Any] | None
    char_start: int
    char_end: int
    score: float


async def search(
    session: AsyncSession,
    owner: uuid.UUID,
    query: str,
    top_k: int = 10,
) -> list[Hit]:
    qvec = (await embedding.embed_texts([query]))[0]
    distance = Embedding.vector.cosine_distance(qvec)
    rows = (
        await session.execute(
            select(
                Document.id,
                Chunk.id,
                Chunk.ordinal,
                Chunk.text,
                Chunk.section_meta,
                Chunk.char_start,
                Chunk.char_end,
                distance.label("distance"),
            )
            .select_from(Embedding)
            .join(Chunk, Chunk.id == Embedding.chunk_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                owner_filter(owner),
                Document.supersedes_id.is_(None),
                Document.state != DocState.soft_deleted,
            )
            .order_by(distance)
            .limit(top_k)
        )
    ).all()
    return [
        Hit(
            document_id=r[0],
            chunk_id=r[1],
            ordinal=r[2],
            text=r[3],
            section_meta=r[4],
            char_start=r[5],
            char_end=r[6],
            score=1.0 - float(r[7]),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class EntityRef:
    key: str
    name: str
    type: str


@dataclass(frozen=True)
class RelRef:
    subject_key: str
    predicate: str
    object_key: str
    source_doc_id: str | None


@dataclass(frozen=True)
class Fanout:
    entities_per_doc: int
    neighbors_per_entity: int


@dataclass(frozen=True)
class Expansion:
    entities: list[EntityRef]
    relationships: list[RelRef]
    linked_document_ids: list[uuid.UUID]


def _default_fanout() -> Fanout:
    s = get_settings()
    return Fanout(s.expand_entities_per_doc, s.expand_neighbors_per_entity)


async def expand(
    session: AsyncSession,
    owner: uuid.UUID,
    seed_document_ids: list[uuid.UUID],
    *,
    fanout: Fanout | None = None,
) -> Expansion:
    fanout = fanout or _default_fanout()
    seeds = [str(d) for d in seed_document_ids]
    if not seeds:
        return Expansion(entities=[], relationships=[], linked_document_ids=[])

    entities: dict[str, EntityRef] = {}
    per_doc: dict[str, set[str]] = {}
    for doc_id, key, name, type_, _conf in await graph.mentioned_entities(
        session, owner, seeds
    ):
        seen = per_doc.setdefault(doc_id, set())
        if key not in entities and len(seen) >= fanout.entities_per_doc:
            continue
        seen.add(key)
        entities.setdefault(key, EntityRef(key=key, name=name, type=type_))

    relationships: list[RelRef] = []
    per_entity: dict[str, int] = {}
    for subj, pred, obj, src, _conf in await graph.entity_neighbors(
        session, owner, list(entities)
    ):
        if per_entity.get(subj, 0) >= fanout.neighbors_per_entity:
            continue
        per_entity[subj] = per_entity.get(subj, 0) + 1
        relationships.append(
            RelRef(subject_key=subj, predicate=pred, object_key=obj, source_doc_id=src)
        )

    reach = list(entities) + [r.object_key for r in relationships]
    seed_set = set(seeds)
    linked = sorted(
        {
            uuid.UUID(doc_id)
            for _key, doc_id in await graph.docs_for_entities(session, owner, reach)
            if doc_id not in seed_set
        }
    )
    return Expansion(
        entities=list(entities.values()),
        relationships=relationships,
        linked_document_ids=linked,
    )


async def search_graph(
    session: AsyncSession,
    owner: uuid.UUID,
    query: str,
    top_k: int = 10,
) -> tuple[list[Hit], Expansion]:
    hits = await search(session, owner, query, top_k)
    seeds: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for h in hits:
        if h.document_id not in seen:
            seen.add(h.document_id)
            seeds.append(h.document_id)
    expansion = await expand(session, owner, seeds)
    return hits, expansion
