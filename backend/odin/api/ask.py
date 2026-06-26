"""Ask routes (grounded, cited answer)."""

from dataclasses import asdict

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import AskCitation, AskIn, AskOut
from odin.services import answering

router = APIRouter()


@router.post("", response_model=AskOut)
async def ask(principal: PrincipalDep, session: SessionDep, body: AskIn) -> AskOut:
    history = (
        [{"role": t.role, "content": t.content} for t in body.history] if body.history else None
    )
    result = await answering.answer(session, principal.id, body.question, history=history)
    return AskOut(
        answer=result.text,
        confident=result.confident,
        citations=[AskCitation(**asdict(c)) for c in result.citations],
    )
