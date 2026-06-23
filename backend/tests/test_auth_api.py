def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_whoami_returns_principal(client, admin):
    user, token = admin
    r = await client.get("/auth/whoami", headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "admin@example.com"
    assert body["user"]["is_initial_admin"] is True
    assert any(scope["type"] == "personal" for scope in body["scopes"])


async def test_missing_token_is_401(client):
    r = await client.get("/auth/whoami")
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "auth_error"


async def test_invalid_token_is_401(client):
    r = await client.get("/auth/whoami", headers=_bearer("odin_pat_nope"))
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "auth_error"
