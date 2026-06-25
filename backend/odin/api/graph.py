"""Graph routes: explore entities/relationships, inspect mutation history."""

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import NotFoundError
from odin.schemas import EntityOut, EntitySummary, MutationOut, RelationshipOut
from odin.services import graph
from odin.tenancy import resolve_scope_set

router = APIRouter()


@router.get("/entities", response_model=list[EntitySummary])
async def find_entities(
    principal: PrincipalDep, session: SessionDep, q: str
) -> list[EntitySummary]:
    scope_set = await resolve_scope_set(session, principal)
    rows = await graph.find_entities(session, scope_set, q)
    return [EntitySummary(key=k, name=n, type=t) for k, n, t in rows]


@router.get("/entities/{key}", response_model=EntityOut)
async def read_entity(principal: PrincipalDep, session: SessionDep, key: str) -> EntityOut:
    scope_set = await resolve_scope_set(session, principal)
    entity = await graph.read_entity(session, scope_set, key)
    if entity is None:
        raise NotFoundError(f"entity not found: {key}")
    return EntityOut(
        key=entity["key"],
        name=entity["name"],
        type=entity["type"],
        aliases=entity["aliases"],
        relationships=[RelationshipOut(**r) for r in entity["relationships"]],
    )


@router.get("/entities/{key}/history", response_model=list[MutationOut])
async def entity_history(
    principal: PrincipalDep, session: SessionDep, key: str
) -> list[MutationOut]:
    scope_set = await resolve_scope_set(session, principal)
    rows = await graph.entity_history(session, scope_set, key)
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
