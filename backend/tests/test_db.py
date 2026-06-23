from odin.graphdb import cypher
from sqlalchemy import text


async def test_relational_roundtrip(db_session):
    result = await db_session.execute(text("SELECT 42"))
    assert result.scalar_one() == 42


async def test_age_return_one(db_session):
    rows = await cypher(db_session, "odin", "RETURN 1")
    assert rows == [(1,)]


async def test_age_param(db_session):
    rows = await cypher(db_session, "odin", "RETURN $n", {"n": 7})
    assert rows == [(7,)]
