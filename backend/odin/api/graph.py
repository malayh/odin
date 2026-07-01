"""Graph routes: explore entities/relationships, deterministic editing, objectives."""

from fastapi import APIRouter, Query

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import NotFoundError
from odin.schemas import (
    EdgeIn,
    EntityIn,
    EntityOut,
    EntityRenameIn,
    EntitySummary,
    MutationOut,
    MutationResult,
    ObjectiveIn,
    ObjectiveOut,
    RelationshipOut,
    SubgraphEdge,
)
from odin.services import graph, objectives

router = APIRouter()


@router.get("/entities", response_model=list[EntitySummary])
async def list_entities(
    principal: PrincipalDep,
    session: SessionDep,
    q: str | None = None,
    type_filter: str | None = Query(None, alias="type"),
    limit: int = 50,
    offset: int = 0,
) -> list[EntitySummary]:
    if q is not None:
        rows = await graph.find_entities(session, principal.id, q)
    else:
        rows = await graph.list_entities(session, principal.id, type_filter, limit, offset)
    return [EntitySummary(key=k, name=n, type=t) for k, n, t in rows]


@router.post("/entities", response_model=MutationResult)
async def add_entity(
    body: EntityIn, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await graph.create_entity(
        session, principal.id, body.type, body.name, dry_run=dry_run
    )
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.get("/entities/{key}", response_model=EntityOut)
async def read_entity(
    principal: PrincipalDep, session: SessionDep, key: str, depth: int = 1
) -> EntityOut:
    entity = await graph.read_entity(session, principal.id, key, depth)
    if entity is None:
        raise NotFoundError(f"entity not found: {key}")
    return EntityOut(
        key=entity["key"],
        name=entity["name"],
        type=entity["type"],
        aliases=entity["aliases"],
        relationships=[RelationshipOut(**r) for r in entity["relationships"]],
        subgraph=[SubgraphEdge(**e) for e in entity["subgraph"]],
    )


@router.patch("/entities/{key}", response_model=MutationResult)
async def rename_entity(
    key: str,
    body: EntityRenameIn,
    principal: PrincipalDep,
    session: SessionDep,
    dry_run: bool = False,
) -> MutationResult:
    result = await graph.rename_entity(
        session, principal.id, key, body.new_name, dry_run=dry_run
    )
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.delete("/entities/{key}", response_model=MutationResult)
async def drop_entity(
    key: str, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await graph.drop_entity(session, principal.id, key, dry_run=dry_run)
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.get("/entities/{key}/history", response_model=list[MutationOut])
async def entity_history(
    principal: PrincipalDep, session: SessionDep, key: str
) -> list[MutationOut]:
    rows = await graph.entity_history(session, principal.id, key)
    return [
        MutationOut(
            seq=r.seq,
            actor=r.actor,
            op=r.op,
            payload=r.payload,
            rationale=r.rationale,
            confidence=r.confidence,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/edges", response_model=MutationResult)
async def add_edge(
    body: EdgeIn, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await graph.add_manual_relationship(
        session, principal.id, body.subject_key, body.predicate, body.object_key, dry_run=dry_run
    )
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.delete("/edges", response_model=MutationResult)
async def remove_edge(
    principal: PrincipalDep,
    session: SessionDep,
    subject_key: str,
    predicate: str,
    object_key: str,
    dry_run: bool = False,
) -> MutationResult:
    result = await graph.remove_relationship(
        session, principal.id, subject_key, predicate, object_key, dry_run=dry_run
    )
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.post("/objectives", response_model=MutationResult)
async def add_objective(
    body: ObjectiveIn, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await objectives.create(session, principal.id, body.text, dry_run=dry_run)
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)


@router.get("/objectives", response_model=list[ObjectiveOut])
async def list_objectives(principal: PrincipalDep, session: SessionDep) -> list[ObjectiveOut]:
    rows = await objectives.list_for_owner(session, principal.id)
    return [ObjectiveOut(**r) for r in rows]


@router.get("/objectives/{objective_id}", response_model=ObjectiveOut)
async def get_objective(
    objective_id: str, principal: PrincipalDep, session: SessionDep
) -> ObjectiveOut:
    row = await objectives.get_for_owner(session, principal.id, objective_id)
    return ObjectiveOut(**row)


@router.delete("/objectives/{objective_id}", response_model=MutationResult)
async def drop_objective(
    objective_id: str, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await objectives.drop(session, principal.id, objective_id, dry_run=dry_run)
    if result["applied"]:
        await session.commit()
    return MutationResult(**result)
