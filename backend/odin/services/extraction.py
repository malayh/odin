"""Single-pass LLM extraction of entities + typed relationships per the ontology."""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.models import Chunk
from odin.services import llm, ontology


class ExtractedEntity(BaseModel):
    name: str
    type: str
    confidence: float = 0.5


class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = 0.5


class ExtractedObjective(BaseModel):
    text: str
    confidence: float = 0.5


class Extracted(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    objectives: list[ExtractedObjective] = Field(default_factory=list)


def _norm_objective(text: str) -> str:
    return " ".join(text.split()).lower()


def _prompt(text: str) -> str:
    return (
        "Extract entities, typed relationships, and objectives from the text as JSON.\n"
        f"Entity types (prefer these, propose others only if needed): "
        f"{', '.join(sorted(ontology.ENTITY_TYPES))}.\n"
        f"Relationship predicates (prefer these): {', '.join(sorted(ontology.PREDICATES))}.\n"
        "Objectives are concrete goals or intentions the author or subjects are trying to "
        "achieve (e.g. 'ship Atlas by Q3', 'close the Series B'). Extract only clear goals, "
        "not general facts. Phrase each as a short imperative.\n"
        'Return JSON {"entities":[{"name","type","confidence"}],'
        '"relations":[{"subject","predicate","object","confidence"}],'
        '"objectives":[{"text","confidence"}]}. '
        "subject/object must be names present in entities. confidence is in [0,1].\n\n"
        f"TEXT:\n{text}"
    )


async def extract(session: AsyncSession, document_id: uuid.UUID) -> Extracted:
    chunks = (
        (
            await session.execute(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
            )
        )
        .scalars()
        .all()
    )
    entities: dict[str, ExtractedEntity] = {}
    relations: dict[tuple[str, str, str], ExtractedRelation] = {}
    objectives: dict[str, ExtractedObjective] = {}
    for chunk in chunks:
        result = await llm.complete_json(_prompt(chunk.text), Extracted)
        for e in result.entities:
            type_norm, _ = ontology.normalize_type(e.type)
            key = ontology.entity_key(e.name, e.type)
            ecur = entities.get(key)
            if ecur is None or e.confidence > ecur.confidence:
                entities[key] = ExtractedEntity(
                    name=e.name, type=type_norm, confidence=e.confidence
                )
        for r in result.relations:
            pred_norm, _ = ontology.normalize_predicate(r.predicate)
            rk = (r.subject, pred_norm, r.object)
            rcur = relations.get(rk)
            if rcur is None or r.confidence > rcur.confidence:
                relations[rk] = ExtractedRelation(
                    subject=r.subject, predicate=pred_norm, object=r.object, confidence=r.confidence
                )
        for o in result.objectives:
            ok = _norm_objective(o.text)
            ocur = objectives.get(ok)
            if ok and (ocur is None or o.confidence > ocur.confidence):
                objectives[ok] = ExtractedObjective(text=o.text, confidence=o.confidence)
    return Extracted(
        entities=list(entities.values()),
        relations=list(relations.values()),
        objectives=list(objectives.values()),
    )
