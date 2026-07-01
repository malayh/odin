"""Sleep-cycle routes: trigger + poll consolidate/dream (single-flight per user)."""

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.models import User
from odin.schemas import SleepRunOut, SleepStatusOut
from odin.services import sleep

router = APIRouter()


async def _trigger(type_: str, principal: User, session: SessionDep) -> SleepRunOut:
    run = await sleep.trigger(session, principal.id, type_)
    return SleepRunOut.model_validate(run)


async def _status(type_: str, principal: User, session: SessionDep) -> SleepStatusOut:
    result = await sleep.status(session, principal.id, type_)
    run = result["run"]
    return SleepStatusOut(
        run=SleepRunOut.model_validate(run) if run is not None else None,
        waiting_behind=result["waiting_behind"],
    )


@router.post("/consolidate", response_model=SleepRunOut, status_code=201)
async def trigger_consolidate(principal: PrincipalDep, session: SessionDep) -> SleepRunOut:
    return await _trigger("consolidate", principal, session)


@router.get("/consolidate/status", response_model=SleepStatusOut)
async def consolidate_status(principal: PrincipalDep, session: SessionDep) -> SleepStatusOut:
    return await _status("consolidate", principal, session)


@router.post("/dream", response_model=SleepRunOut, status_code=201)
async def trigger_dream(principal: PrincipalDep, session: SessionDep) -> SleepRunOut:
    return await _trigger("dream", principal, session)


@router.get("/dream/status", response_model=SleepStatusOut)
async def dream_status(principal: PrincipalDep, session: SessionDep) -> SleepStatusOut:
    return await _status("dream", principal, session)
