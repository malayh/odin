from sqlalchemy import text


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_db_roundtrip(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
