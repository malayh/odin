from odin.models import User
from odin.seed import seed_admin
from odin.services.auth import issue_token
from odin.services.users import create_user
from sqlalchemy import func, select


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_admin_creates_user_and_token(client, admin):
    _, token = admin
    auth = _bearer(token)

    r = await client.post("/admin/users", json={"email": "member@example.com"}, headers=auth)
    assert r.status_code == 201
    member = r.json()

    r = await client.post(f"/admin/users/{member['id']}/tokens", json={}, headers=auth)
    assert r.status_code == 201
    assert r.json()["token"].startswith("odin_pat_")


async def test_non_admin_cannot_administer(client, db_session):
    user = await create_user(db_session, "plain@example.com")
    token, _ = await issue_token(db_session, user)
    r = await client.post(
        "/admin/users", json={"email": "nope@example.com"}, headers=_bearer(token)
    )
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "forbidden"


async def test_seed_is_idempotent(db_session):
    await seed_admin(db_session, "idemp@example.com")
    await seed_admin(db_session, "idemp@example.com")
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "idemp@example.com")
    )
    assert count == 1
