import uuid

import pytest
from odin.services import blobs
from odin.services.auth import issue_token
from odin.services.users import create_user


@pytest.fixture(autouse=True)
def _fake_blob_put(monkeypatch):
    async def fake_put(data: bytes) -> str:
        return f"s3://odin/{blobs.content_hash(data)}"

    monkeypatch.setattr(blobs, "put", fake_put)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _ingest(client, token, key="a.md"):
    r = await client.post(
        "/ingest",
        headers=_bearer(token),
        data={"key": key},
        files={"file": (key, b"hi there", "text/markdown")},
    )
    return r.json()["job_id"]


async def test_job_status_is_pollable(client, admin):
    _, token = admin
    job_id = await _ingest(client, token)
    r = await client.get(f"/jobs/{job_id}", headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == job_id
    assert body["type"] == "ingest"
    assert body["state"] == "pending"


async def test_other_user_cannot_read_job(client, admin, db_session):
    _, token = admin
    job_id = await _ingest(client, token, key="secret.md")
    other = await create_user(db_session, "other-job@example.com")
    other_token, _ = await issue_token(db_session, other)
    r = await client.get(f"/jobs/{job_id}", headers=_bearer(other_token))
    assert r.status_code == 404


async def test_unknown_job_is_404(client, admin):
    _, token = admin
    r = await client.get(f"/jobs/{uuid.uuid4()}", headers=_bearer(token))
    assert r.status_code == 404


async def test_list_jobs_scoped_to_owner(client, admin, db_session):
    _, token = admin
    job_id = await _ingest(client, token, key="mine.md")
    r = await client.get("/jobs", headers=_bearer(token))
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()}
    assert job_id in ids

    other = await create_user(db_session, "other-list@example.com")
    other_token, _ = await issue_token(db_session, other)
    r2 = await client.get("/jobs", headers=_bearer(other_token))
    assert r2.json() == []
