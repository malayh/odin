"""Worker process entrypoint: python -m odin.worker"""

import asyncio

from odin.logging import configure_logging
from odin.worker.app import app


async def _run() -> None:
    async with app.open_async():
        await app.run_worker_async(concurrency=1)


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
