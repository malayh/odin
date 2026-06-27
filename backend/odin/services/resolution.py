"""Entity resolution: embedding + LLM canonicalization into canonical entities with aliases."""

import asyncio
import logging
import math
import uuid
from collections import defaultdict

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from odin.config import get_settings
from odin.services import embedding, graph, llm, mutations, ontology
from odin.services.extraction import Extracted

logger = logging.getLogger(__name__)

_THRESHOLD = 0.5

_DOSSIER_MAX_FACTS = 20
_DOSSIER_MAX_COOCCURRING = 20
_DOSSIER_MAX_DOCS = 10
_JUDGE_MAX_TOKENS = 16384


class _Confirm(BaseModel):
    same: bool


class _SkepticVerdict(BaseModel):
    distinct: bool
    confidence: float
    rationale: str


class _JudgeVerdict(BaseModel):
    same: bool
    confidence: float
    rationale: str


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
    result = await llm.complete_json(
        prompt, _Confirm, model=get_settings().tier2_model, max_tokens=_JUDGE_MAX_TOKENS
    )
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


def _dossier_text(
    name: str,
    type_: str,
    aliases: list[str],
    outgoing: list[str],
    incoming: list[str],
    cooccurring: list[str],
    docs: list[str],
) -> str:
    lines = [f'"{name}" ({type_})']
    if aliases:
        lines.append("aliases: " + ", ".join(aliases[:_DOSSIER_MAX_FACTS]))
    if outgoing:
        lines.append("relates to: " + "; ".join(outgoing[:_DOSSIER_MAX_FACTS]))
    if incoming:
        lines.append("related from: " + "; ".join(incoming[:_DOSSIER_MAX_FACTS]))
    if cooccurring:
        lines.append("co-occurs with: " + "; ".join(cooccurring[:_DOSSIER_MAX_COOCCURRING]))
    if docs:
        lines.append("asserted in: " + "; ".join(docs[:_DOSSIER_MAX_DOCS]))
    return "\n".join(lines)


async def _build_dossiers(
    session: AsyncSession, owner: uuid.UUID, entities: list[tuple[str, str, str]]
) -> dict[str, str]:
    keys = [e[0] for e in entities]
    name_by = {e[0]: e[1] for e in entities}
    type_by = {e[0]: e[2] for e in entities}

    outgoing: dict[str, list[str]] = defaultdict(list)
    for k, pred, obj in await graph.owner_entity_facts(session, owner, keys):
        outgoing[k].append(f"{pred} {obj}")
    incoming: dict[str, list[str]] = defaultdict(list)
    for k, pred, subj in await graph.owner_entity_incoming(session, owner, keys):
        incoming[k].append(f"{subj} {pred}")
    aliases: dict[str, set[str]] = defaultdict(set)
    for k, alias in await graph.entity_aliases(session, owner, keys):
        if alias:
            aliases[k].add(alias)

    doc_ids_by: dict[str, list[str]] = defaultdict(list)
    all_doc_ids: set[str] = set()
    for k, did in await graph.docs_for_entities(session, owner, keys):
        doc_ids_by[k].append(did)
        all_doc_ids.add(did)
    titles = await graph.doc_keys(session, list(all_doc_ids))
    ents_by_doc: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for did, k, nm, tp, _ in await graph.mentioned_entities(session, owner, list(all_doc_ids)):
        ents_by_doc[did].append((k, nm, tp))

    dossiers: dict[str, str] = {}
    for k in keys:
        cooccurring: list[str] = []
        seen: set[str] = set()
        for did in doc_ids_by.get(k, []):
            for ck, cn, ct in ents_by_doc.get(did, []):
                if ck == k or ck in seen:
                    continue
                seen.add(ck)
                cooccurring.append(f"{cn} ({ct})")
        doc_titles = sorted({titles.get(d, d) for d in doc_ids_by.get(k, [])})
        dossiers[k] = _dossier_text(
            name_by[k],
            type_by[k],
            sorted(aliases.get(k, set())),
            outgoing.get(k, []),
            incoming.get(k, []),
            cooccurring,
            doc_titles,
        )
    return dossiers


async def _skeptic(dossier_a: str, dossier_b: str) -> _SkepticVerdict:
    prompt = (
        "You audit a proposed entity merge in a knowledge graph. Find concrete, "
        "evidence-based reasons that A and B are DIFFERENT real-world entities, using ONLY "
        "the dossiers below. Do not speculate or invent distinctions; similar or different "
        "names are not by themselves evidence. A real distinction is a concrete contradiction "
        "grounded in the evidence: incompatible attributes or roles, or neighborhoods and "
        "co-occurrences that clearly belong to different real-world things. If the dossiers "
        "contain no such concrete contradiction, return distinct=false with low confidence. "
        "When distinct=true, the rationale MUST cite the specific conflicting evidence.\n"
        f"A:\n{dossier_a}\n\nB:\n{dossier_b}\n\n"
        'Return JSON {"distinct": true|false, "confidence": 0..1, "rationale": "..."}. '
        "confidence is how strongly the cited evidence supports a real distinction."
    )
    return await llm.complete_json(prompt, _SkepticVerdict, max_tokens=_JUDGE_MAX_TOKENS)


async def _neutral_judge(dossier_a: str, dossier_b: str) -> _JudgeVerdict:
    prompt = (
        "You are canonicalizing entities in a knowledge graph. Using the dossiers below "
        "(names, types, aliases, relationships, co-occurring entities, and source documents), "
        "decide whether A and B refer to the same real-world entity. Base your judgment on "
        "the evidence.\n"
        f"A:\n{dossier_a}\n\nB:\n{dossier_b}\n\n"
        'Return JSON {"same": true|false, "confidence": 0..1, "rationale": "..."}. '
        "confidence is how certain you are."
    )
    return await llm.complete_json(
        prompt, _JudgeVerdict, model=get_settings().tier2_model, max_tokens=_JUDGE_MAX_TOKENS
    )


async def _judge_pair(dossier_a: str, dossier_b: str) -> tuple[bool, float, str]:
    settings = get_settings()
    skeptic = await _skeptic(dossier_a, dossier_b)
    if skeptic.distinct and skeptic.confidence >= settings.consolidation_skeptic_floor:
        return False, skeptic.confidence, f"skeptic refuted: {skeptic.rationale}"
    n = settings.consolidation_neutral_judges
    votes = await asyncio.gather(*(_neutral_judge(dossier_a, dossier_b) for _ in range(n)))
    same = [v for v in votes if v.same]
    if len(same) < settings.consolidation_neutral_quorum:
        return False, 0.0, "neutral quorum not met"
    mean_conf = sum(v.confidence for v in same) / len(same)
    if mean_conf < settings.consolidation_confidence_floor:
        return False, mean_conf, "confidence floor not met"
    return True, mean_conf, "; ".join(v.rationale for v in same)


async def deep_consolidate(
    session: AsyncSession,
    owner: uuid.UUID,
    *,
    keys: list[str] | None = None,
) -> int:
    entities = await graph.list_owner_entities(session, owner)
    if keys is not None:
        keyset = set(keys)
        entities = [e for e in entities if e[0] in keyset]
    if len(entities) < 2:
        return 0
    ekeys = [e[0] for e in entities]
    names = [e[1] for e in entities]
    types = [e[2] for e in entities]
    vecs = await embedding.embed_texts(names)
    dossiers = await _build_dossiers(session, owner, entities)
    gate = get_settings().consolidation_cosine_gate

    parent = list(range(len(ekeys)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    evidence: dict[int, tuple[float, str]] = {}
    for i in range(len(ekeys)):
        for j in range(i + 1, len(ekeys)):
            if find(i) == find(j) or _cosine(vecs[i], vecs[j]) < gate:
                continue
            try:
                merge, conf, rationale = await _judge_pair(dossiers[ekeys[i]], dossiers[ekeys[j]])
            except Exception:
                logger.warning("deep_consolidate judge failed for %s ~ %s; skipping",
                               ekeys[i], ekeys[j])
                continue
            if merge:
                union(i, j)
                evidence[i] = (conf, rationale)
                evidence[j] = (conf, rationale)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(ekeys)):
        clusters[find(i)].append(i)

    merged = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        canon = max(members, key=lambda m: (len(names[m]), names[m], ekeys[m]))
        ckey, cname, ctype = ekeys[canon], names[canon], types[canon]
        for m in members:
            if m == canon:
                continue
            conf, rationale = evidence[m]
            await graph.merge_nodes(session, ckey, cname, ctype, ekeys[m], str(owner))
            await mutations.log(
                session,
                actor="resolver",
                op="node_merge",
                payload={
                    "canonical_key": ckey,
                    "absorbed_key": ekeys[m],
                    "absorbed_name": names[m],
                    "absorbed_type": types[m],
                    "owner": str(owner),
                },
                rationale=rationale,
                confidence=conf,
            )
            merged += 1
    return merged
