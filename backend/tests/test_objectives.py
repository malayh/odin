import uuid

import pytest
from odin.errors import NotFoundError
from odin.services import objectives


async def test_create_list_drop_roundtrip(db_session):
    owner = uuid.uuid4()
    created = await objectives.create(db_session, owner, "ship L5")
    assert created["applied"] is True
    assert created["id"]

    rows = await objectives.list_for_owner(db_session, owner)
    assert [r["text"] for r in rows] == ["ship L5"]
    assert rows[0]["id"] == created["id"]

    dropped = await objectives.drop(db_session, owner, created["id"])
    assert dropped["applied"] is True
    assert await objectives.list_for_owner(db_session, owner) == []


async def test_owner_isolation(db_session):
    a, b = uuid.uuid4(), uuid.uuid4()
    await objectives.create(db_session, a, "a-goal")
    await objectives.create(db_session, b, "b-goal")
    assert [r["text"] for r in await objectives.list_for_owner(db_session, a)] == ["a-goal"]
    assert [r["text"] for r in await objectives.list_for_owner(db_session, b)] == ["b-goal"]


async def test_dry_run_does_not_write(db_session):
    owner = uuid.uuid4()
    preview = await objectives.create(db_session, owner, "ship L5", dry_run=True)
    assert preview["applied"] is False
    assert await objectives.list_for_owner(db_session, owner) == []


async def test_drop_missing_raises(db_session):
    with pytest.raises(NotFoundError):
        await objectives.drop(db_session, uuid.uuid4(), "no-such-id")
