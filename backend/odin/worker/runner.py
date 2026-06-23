"""Worker loop: claim jobs from the queue and dispatch to handlers."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from odin.config import get_settings
from odin.logging import configure_logging
from odin.worker.handlers import HANDLERS, Handler

log = logging.getLogger("odin.worker")

Job = dict[str, Any]
ClaimFn = Callable[[], Awaitable[Job | None]]


async def _default_claim() -> Job | None:
    return None


async def _dispatch(job: Job, handlers: dict[str, Handler]) -> None:
    handler = handlers.get(job.get("type", ""))
    if handler is None:
        log.warning("no handler for job type=%s", job.get("type"))
        return
    await handler(job)


async def _run(claim: ClaimFn, handlers: dict[str, Handler], stop: asyncio.Event) -> None:
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
        except Exception:
            log.exception("handler crashed job=%s", job.get("id"))
    log.info("worker stopped")


async def _amain(claim: ClaimFn | None = None) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await _run(claim or _default_claim, HANDLERS, stop)


def main() -> None:
    configure_logging()
    asyncio.run(_amain())
