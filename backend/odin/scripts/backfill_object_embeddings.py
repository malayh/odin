"""One-off: embed entity names that predate live embedding upkeep."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.db import SessionLocal
from odin.models import ObjectEmbedding, User
from odin.services import embedding, graph


async def backfill_owner(session: AsyncSession, owner: uuid.UUID) -> int:
    entities = await graph.list_owner_entities(session, owner)
    if not entities:
        return 0
    existing = set(
        (
            await session.execute(
                select(ObjectEmbedding.object_id).where(
                    ObjectEmbedding.object_type == "entity",
                    ObjectEmbedding.owner_user_id == owner,
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [(key, name) for key, name, _type in entities if key not in existing]
    await embedding.upsert_object_embeddings(session, "entity", "name", owner, missing)
    return len(missing)


async def _run() -> None:
    async with SessionLocal() as session:
        owners = (await session.execute(select(User.id))).scalars().all()
        total = 0
        for owner in owners:
            n = await backfill_owner(session, owner)
            total += n
            if n:
                print(f"{owner}: embedded {n} entities")
        await session.commit()
        print(f"done: {total} entity embeddings backfilled")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
