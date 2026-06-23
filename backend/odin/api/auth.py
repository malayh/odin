"""Auth routes: login, whoami, token management."""

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import ScopeOut, UserOut, WhoamiOut
from odin.tenancy import resolve_scope_set

router = APIRouter()


@router.get("/whoami", response_model=WhoamiOut)
async def whoami(principal: PrincipalDep, session: SessionDep) -> WhoamiOut:
    scope_set = await resolve_scope_set(session, principal)
    scopes = [ScopeOut(type="personal", id=principal.id, role=None)]
    scopes.extend(
        ScopeOut(type="org", id=org_id, role=role) for org_id, role in scope_set.roles.items()
    )
    return WhoamiOut(user=UserOut.model_validate(principal), scopes=scopes)
