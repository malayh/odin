"""Sleep-cycle orchestration: trigger consolidate/dream (single-flight per type) + status.

Concurrency model (design_doc/003): each type is single-flight (at most one queued-or-running
run per type, gated here and by the sleep_runs partial unique index); the two types are mutually
exclusive at run time via a per-user Procrastinate ``lock``, so triggering the second while the
first runs simply queues it.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import ConflictError, ValidationError
from odin.models import SleepRun, SleepState
from odin.worker.tasks import consolidate as consolidate_task
from odin.worker.tasks import dream as dream_task

_TASKS: dict[str, Any] = {"consolidate": consolidate_task, "dream": dream_task}


def _require_type(type_: str) -> None:
    if type_ not in _TASKS:
        raise ValidationError(f"unknown sleep type: {type_}")


async def trigger(
    session: AsyncSession, owner: uuid.UUID, type_: str, *, full: bool = False
) -> SleepRun:
    _require_type(type_)
    active = await session.scalar(
        select(SleepRun).where(
            SleepRun.owner_user_id == owner,
            SleepRun.type == type_,
            SleepRun.state.in_((SleepState.queued, SleepState.running)),
        )
    )
    if active is not None:
        raise ConflictError(f"a {type_} run is already {active.state.value}")

    run = SleepRun(owner_user_id=owner, type=type_, state=SleepState.queued)
    session.add(run)
    await session.flush()

    task_args: dict[str, Any] = {"run_id": str(run.id)}
    if type_ == "consolidate":
        task_args["full"] = full

    connection = (await (await session.connection()).get_raw_connection()).driver_connection
    await (
        _TASKS[type_]
        .configure(
            connection=connection,
            lock=f"sleep:{owner}",
            queueing_lock=f"{type_}:{owner}",
        )
        .defer_async(**task_args)
    )
    await session.commit()
    return run


async def status(session: AsyncSession, owner: uuid.UUID, type_: str) -> dict[str, Any]:
    _require_type(type_)
    latest = await session.scalar(
        select(SleepRun)
        .where(SleepRun.owner_user_id == owner, SleepRun.type == type_)
        .order_by(SleepRun.queued_at.desc())
        .limit(1)
    )
    waiting_behind = None
    if latest is not None and latest.state == SleepState.queued:
        running = await session.scalar(
            select(SleepRun).where(
                SleepRun.owner_user_id == owner,
                SleepRun.state == SleepState.running,
            )
        )
        waiting_behind = running.type if running is not None else None
    return {"run": latest, "waiting_behind": waiting_behind}
