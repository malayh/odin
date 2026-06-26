"""Auth routes: whoami."""

from fastapi import APIRouter

from odin.api.deps import PrincipalDep
from odin.schemas import UserOut, WhoamiOut

router = APIRouter()


@router.get("/whoami", response_model=WhoamiOut)
async def whoami(principal: PrincipalDep) -> WhoamiOut:
    return WhoamiOut(user=UserOut.model_validate(principal))
