import asyncio

from odin.worker.runner import _dispatch, _run


async def _record(seen: list, job: dict) -> None:
    seen.append(job)


async def test_dispatch_calls_registered_handler():
    seen: list = []
    handlers = {"x": lambda job: _record(seen, job)}
    await _dispatch({"type": "x", "id": 1}, handlers)
    assert seen == [{"type": "x", "id": 1}]


async def test_dispatch_unknown_type_is_noop():
    await _dispatch({"type": "missing"}, {})


async def test_run_processes_then_stops_cleanly():
    stop = asyncio.Event()
    jobs = [{"type": "x", "id": 1}]
    handled: list = []

    async def claim() -> dict | None:
        if jobs:
            return jobs.pop(0)
        stop.set()
        return None

    handlers = {"x": lambda j: _record(handled, j)}
    await asyncio.wait_for(_run(claim, handlers, stop), timeout=5)
    assert handled == [{"type": "x", "id": 1}]
