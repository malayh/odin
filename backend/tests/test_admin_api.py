from odin.models import User
from odin.seed import seed_admin
from odin.services.auth import issue_token
from odin.services.orgs import create_user
from sqlalchemy import func, select


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_admin_creates_org_invites_and_assigns_roles(client, admin):
    _, token = admin
    auth = _bearer(token)

    r = await client.post("/admin/users", json={"email": "member@example.com"}, headers=auth)
    assert r.status_code == 201
    member = r.json()

    r = await client.post("/admin/orgs", json={"name": "Acme"}, headers=auth)
    assert r.status_code == 201
    org = r.json()

    r = await client.post(
        f"/admin/orgs/{org['id']}/members",
        json={"user_id": member["id"], "role": "viewer"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["role"] == "viewer"

    r = await client.put(
        f"/admin/orgs/{org['id']}/members/{member['id']}",
        json={"role": "editor"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "editor"

    r = await client.post(f"/admin/users/{member['id']}/tokens", json={}, headers=auth)
    assert r.status_code == 201
    assert r.json()["token"].startswith("odin_pat_")


async def test_non_admin_cannot_administer(client, db_session):
    user = await create_user(db_session, "plain@example.com")
    token, _ = await issue_token(db_session, user)
    r = await client.post("/admin/orgs", json={"name": "Nope"}, headers=_bearer(token))
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "forbidden"


async def test_org_viewer_cannot_add_members(client, admin):
    _, admin_token = admin
    auth = _bearer(admin_token)

    r = await client.post("/admin/users", json={"email": "viewer@example.com"}, headers=auth)
    viewer = r.json()
    r = await client.post("/admin/orgs", json={"name": "ViewerOrg"}, headers=auth)
    org = r.json()
    await client.post(
        f"/admin/orgs/{org['id']}/members",
        json={"user_id": viewer["id"], "role": "viewer"},
        headers=auth,
    )
    r = await client.post(f"/admin/users/{viewer['id']}/tokens", json={}, headers=auth)
    viewer_token = r.json()["token"]

    r = await client.post(
        f"/admin/orgs/{org['id']}/members",
        json={"user_id": viewer["id"], "role": "admin"},
        headers=_bearer(viewer_token),
    )
    assert r.status_code == 403


async def test_seed_is_idempotent(db_session):
    await seed_admin(db_session, "idemp@example.com")
    await seed_admin(db_session, "idemp@example.com")
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "idemp@example.com")
    )
    assert count == 1
