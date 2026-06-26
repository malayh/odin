"""Ask routes (grounded, cited answer)."""

from dataclasses import asdict

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import AskCitation, AskIn, AskOut
from odin.services import answering
from odin.tenancy import Scope, narrow, resolve_scope_set

router = APIRouter()


@router.post("", response_model=AskOut)
async def ask(principal: PrincipalDep, session: SessionDep, body: AskIn) -> AskOut:
    scope_set = await resolve_scope_set(session, principal)
    only = narrow(scope_set, Scope.parse(body.scope, principal.id)) if body.scope else None
    history = (
        [{"role": t.role, "content": t.content} for t in body.history] if body.history else None
    )
    result = await answering.answer(session, scope_set, body.question, only, history=history)
    return AskOut(
        answer=result.text,
        confident=result.confident,
        citations=[AskCitation(**asdict(c)) for c in result.citations],
    )
