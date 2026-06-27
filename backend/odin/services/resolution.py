"""Entity resolution: embedding + LLM canonicalization into canonical entities with aliases."""

import math
import uuid
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from odin.services import embedding, graph, llm, mutations, ontology
from odin.services.extraction import Extracted

_THRESHOLD = 0.5


class _Confirm(BaseModel):
    same: bool


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _describe(name: str, type_: str, facts: list[str]) -> str:
    line = f'"{name}" ({type_})'
    if facts:
        line += " — " + "; ".join(facts)
    return line


async def _confirm_same(
    name_a: str, type_a: str, facts_a: list[str], name_b: str, type_b: str, facts_b: list[str]
) -> bool:
    prompt = (
        "You are canonicalizing entities in a knowledge graph. Decide whether A and B "
        "refer to the same real-world entity, using the names, types, and the facts each "
        "appears in.\n"
        f"A: {_describe(name_a, type_a, facts_a)}\n"
        f"B: {_describe(name_b, type_b, facts_b)}\n"
        'Return JSON {"same": true|false}.'
    )
    result = await llm.complete_json(prompt, _Confirm)
    return result.same


async def resolve(
    session: AsyncSession,
    extracted: Extracted,
    owner: uuid.UUID,
    source_doc_id: str,
    *,
    threshold: float = _THRESHOLD,
) -> dict[str, tuple[str, str, str]]:
    ents = extracted.entities
    if not ents:
        return {}
    new_keys = [ontology.entity_key(e.name, e.type) for e in ents]
    new_types = [ontology.normalize_type(e.type)[0] for e in ents]
    new_key_set = set(new_keys)
    existing = [
        (k, n, t)
        for k, n, t in await graph.list_owner_entities(session, owner)
        if k not in new_key_set
    ]

    n = len(ents)
    names = [e.name for e in ents] + [x[1] for x in existing]
    keys = new_keys + [x[0] for x in existing]
    types = new_types + [x[2] for x in existing]
    in_graph = [False] * n + [True] * len(existing)
    if len(names) < 2:
        return {}
    vecs = await embedding.embed_texts(names)

    new_facts: dict[str, list[str]] = defaultdict(list)
    for rel in extracted.relations:
        new_facts[rel.subject].append(f"{rel.predicate} {rel.object}")
        new_facts[rel.object].append(f"{rel.subject} {rel.predicate}")
    ex_facts: dict[str, list[str]] = defaultdict(list)
    for k, pred, obj in await graph.owner_entity_facts(
        session, owner, [x[0] for x in existing]
    ):
        ex_facts[k].append(f"{pred} {obj}")

    def _facts(idx: int) -> list[str]:
        src = ex_facts.get(keys[idx], []) if in_graph[idx] else new_facts.get(names[idx], [])
        return src[:3]

    parent = list(range(len(names)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if find(i) == find(j) or (in_graph[i] and in_graph[j]):
                continue
            if keys[i] == keys[j]:
                union(i, j)
            elif _cosine(vecs[i], vecs[j]) >= threshold and await _confirm_same(
                names[i], types[i], _facts(i), names[j], types[j], _facts(j)
            ):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(names)):
        clusters[find(i)].append(i)

    merges: dict[str, tuple[str, str, str]] = {}
    for members in clusters.values():
        anchored = [m for m in members if in_graph[m]]
        anchor = max(anchored or members, key=lambda m: (len(names[m]), names[m]))
        fullest = max(members, key=lambda m: (len(names[m]), names[m]))
        ckey, ctype, cname = keys[anchor], types[anchor], names[fullest]
        for m in members:
            if in_graph[m] or keys[m] == ckey:
                continue
            merges[keys[m]] = (ckey, cname, ctype)
            await mutations.log(
                session,
                actor="resolver",
                op="merge",
                payload={
                    "canonical_key": ckey,
                    "absorbed_key": keys[m],
                    "absorbed_name": ents[m].name,
                    "absorbed_type": new_types[m],
                    "source_doc_id": source_doc_id,
                    "alias": ents[m].name,
                    "owner": str(owner),
                    "confidence": ents[m].confidence,
                    "model": "resolver",
                },
                confidence=ents[m].confidence,
            )
    return merges


async def consolidate(
    session: AsyncSession,
    owner: uuid.UUID,
    *,
    threshold: float = _THRESHOLD,
) -> int:
    entities = await graph.list_owner_entities(session, owner)
    if len(entities) < 2:
        return 0
    keys = [e[0] for e in entities]
    names = [e[1] for e in entities]
    types = [e[2] for e in entities]
    vecs = await embedding.embed_texts(names)

    facts: dict[str, list[str]] = defaultdict(list)
    for k, pred, obj in await graph.owner_entity_facts(session, owner, keys):
        facts[k].append(f"{pred} {obj}")

    parent = list(range(len(keys)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if find(i) == find(j):
                continue
            if _cosine(vecs[i], vecs[j]) >= threshold and await _confirm_same(
                names[i], types[i], facts.get(keys[i], [])[:3],
                names[j], types[j], facts.get(keys[j], [])[:3],
            ):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(keys)):
        clusters[find(i)].append(i)

    merged = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        canon = max(members, key=lambda m: (len(names[m]), names[m], keys[m]))
        ckey, cname, ctype = keys[canon], names[canon], types[canon]
        for m in members:
            if m == canon:
                continue
            await graph.merge_nodes(session, ckey, cname, ctype, keys[m], str(owner))
            await mutations.log(
                session,
                actor="resolver",
                op="node_merge",
                payload={
                    "canonical_key": ckey,
                    "absorbed_key": keys[m],
                    "absorbed_name": names[m],
                    "absorbed_type": types[m],
                    "owner": str(owner),
                },
            )
            merged += 1
    return merged
