"""Search routes (owner-filtered retrieval)."""

from dataclasses import asdict

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import SearchHit, SearchIn, SearchOut
from odin.services import retrieval

router = APIRouter()


@router.post("", response_model=SearchOut)
async def search(principal: PrincipalDep, session: SessionDep, body: SearchIn) -> SearchOut:
    hits = await retrieval.search(session, principal.id, body.query, body.top_k)
    return SearchOut(hits=[SearchHit(**asdict(h)) for h in hits])
