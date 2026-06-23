"""Initial-admin seed: create the bootstrap admin and mint a one-time token."""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.db import SessionLocal
from odin.models import User
from odin.services.auth import issue_token


async def seed_admin(session: AsyncSession, email: str) -> tuple[User, str]:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, is_initial_admin=True)
        session.add(user)
        await session.flush()
    elif not user.is_initial_admin:
        user.is_initial_admin = True
        await session.flush()
    plaintext, _ = await issue_token(session, user, name="seed")
    return user, plaintext


async def _run(email: str) -> str:
    async with SessionLocal() as session:
        _, plaintext = await seed_admin(session, email)
        return plaintext


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m odin.seed <email>", file=sys.stderr)
        raise SystemExit(2)
    print(asyncio.run(_run(sys.argv[1])))


if __name__ == "__main__":
    main()
