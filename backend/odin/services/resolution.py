"""Entity resolution: embedding + LLM canonicalization into canonical entities with aliases."""

import math
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from odin.services import embedding, llm, mutations, ontology
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
    if len(ents) < 2:
        return {}
    keys = [ontology.entity_key(e.name, e.type) for e in ents]
    types = [ontology.normalize_type(e.type)[0] for e in ents]
    vecs = await embedding.embed_texts([e.name for e in ents])

    parent = list(range(len(ents)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            if types[i] != types[j] or find(i) == find(j):
                continue
            if keys[i] == keys[j]:
                union(i, j)
            elif _cosine(vecs[i], vecs[j]) >= threshold and await _confirm_same(
                ents[i].name, ents[j].name
            ):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(ents)):
        clusters[find(i)].append(i)

    merges: dict[str, tuple[str, str, str]] = {}
    for members in clusters.values():
        if len({keys[m] for m in members}) < 2:
            continue
        canon = max(members, key=lambda m: (len(ents[m].name), ents[m].confidence))
        ckey, cname, ctype = keys[canon], ents[canon].name, types[canon]
        for m in members:
            if keys[m] == ckey:
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
                    "absorbed_type": types[m],
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
