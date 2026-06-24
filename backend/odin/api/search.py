"""Search routes (scope-filtered retrieval)."""

from dataclasses import asdict

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import SearchHit, SearchIn, SearchOut
from odin.services import retrieval
from odin.tenancy import Scope, narrow, resolve_scope_set

router = APIRouter()


@router.post("", response_model=SearchOut)
async def search(principal: PrincipalDep, session: SessionDep, body: SearchIn) -> SearchOut:
    scope_set = await resolve_scope_set(session, principal)
    only = narrow(scope_set, Scope.parse(body.scope, principal.id)) if body.scope else None
    hits = await retrieval.search(session, scope_set, body.query, only, body.top_k)
    return SearchOut(hits=[SearchHit(**asdict(h)) for h in hits])
