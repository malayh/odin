"""Worker loop: claim jobs from the queue and dispatch to handlers."""

import asyncio
import logging
import signal
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from odin.config import get_settings
from odin.logging import configure_logging
from odin.worker import queue
from odin.worker.handlers import HANDLERS, Handler

log = logging.getLogger("odin.worker")

Job = dict[str, Any]
ClaimFn = Callable[[], Awaitable[Job | None]]
CompleteFn = Callable[[uuid.UUID], Awaitable[None]]
FailFn = Callable[[uuid.UUID, str], Awaitable[None]]


async def _noop_complete(job_id: uuid.UUID) -> None:
    return None


async def _noop_fail(job_id: uuid.UUID, error: str) -> None:
    return None


async def _dispatch(job: Job, handlers: dict[str, Handler]) -> None:
    handler = handlers.get(job.get("type", ""))
    if handler is None:
        log.warning("no handler for job type=%s", job.get("type"))
        return
    await handler(job)


async def _run(
    claim: ClaimFn,
    handlers: dict[str, Handler],
    stop: asyncio.Event,
    complete: CompleteFn = _noop_complete,
    fail: FailFn = _noop_fail,
) -> None:
    interval = get_settings().worker_poll_interval_seconds
    log.info("worker started")
    while not stop.is_set():
        job = await claim()
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass
            continue
        try:
            await _dispatch(job, handlers)
        except Exception as e:
            log.exception("handler crashed job=%s", job.get("id"))
            await fail(job["id"], repr(e))
        else:
            await complete(job["id"])
    log.info("worker stopped")


async def _amain(
    claim: ClaimFn | None = None,
    complete: CompleteFn | None = None,
    fail: FailFn | None = None,
) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await _run(
        claim or queue.claim,
        HANDLERS,
        stop,
        complete or queue.complete,
        fail or queue.fail,
    )


def main() -> None:
    configure_logging()
    asyncio.run(_amain())
