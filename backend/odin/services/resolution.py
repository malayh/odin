"""Entity resolution: embedding + LLM canonicalization into canonical entities with aliases."""

import math
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from odin.services import embedding, graph, llm, mutations, ontology
from odin.services.extraction import Extracted

_THRESHOLD = 0.85


class _Confirm(BaseModel):
    same: bool


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _confirm_same(name_a: str, name_b: str) -> bool:
    prompt = (
        f'Do "{name_a}" and "{name_b}" refer to the same real-world entity? '
        'Return JSON {"same": true|false}.'
    )
    result = await llm.complete_json(prompt, _Confirm)
    return result.same


async def resolve(
    session: AsyncSession,
    extracted: Extracted,
    scope_type: str,
    scope_id: str,
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
        for k, n, t in await graph.list_scope_entities(session, scope_type, scope_id)
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
                names[i], names[j]
            ):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(names)):
        clusters[find(i)].append(i)

    merges: dict[str, tuple[str, str, str]] = {}
    for members in clusters.values():
        anchored = [m for m in members if in_graph[m]]
        if anchored:
            canon = max(anchored, key=lambda m: len(names[m]))
        else:
            canon = max(members, key=lambda m: (len(names[m]), ents[m].confidence))
        ckey, cname, ctype = keys[canon], names[canon], types[canon]
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
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "confidence": ents[m].confidence,
                    "model": "resolver",
                },
                confidence=ents[m].confidence,
            )
    return merges
