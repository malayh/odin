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


async def _ingest(client, token, key="a.md", content=b"hello world"):
    r = await client.post(
        "/ingest",
        headers=_bearer(token),
        data={"key": key},
        files={"file": (key, content, "text/markdown")},
    )
    return r.json()["document_id"]


async def test_list_documents(client, admin):
    _, token = admin
    await _ingest(client, token, key="one.md")
    await _ingest(client, token, key="two.md", content=b"second doc")
    r = await client.get("/documents", headers=_bearer(token))
    assert r.status_code == 200
    keys = {d["key"] for d in r.json()}
    assert {"one.md", "two.md"} <= keys


async def test_get_document(client, admin):
    _, token = admin
    doc_id = await _ingest(client, token, key="get.md")
    r = await client.get(f"/documents/{doc_id}", headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == doc_id
    assert body["key"] == "get.md"
    assert body["state"] == "pending"
    assert body["doc_type"] == "source"


async def test_soft_delete_document(client, admin):
    _, token = admin
    doc_id = await _ingest(client, token, key="del.md")
    r = await client.request("DELETE", f"/documents/{doc_id}", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["applied"] is True
    got = await client.get(f"/documents/{doc_id}", headers=_bearer(token))
    assert got.json()["state"] == "soft_deleted"


async def test_delete_document_dry_run(client, admin):
    _, token = admin
    doc_id = await _ingest(client, token, key="dry.md")
    r = await client.request(
        "DELETE", f"/documents/{doc_id}", headers=_bearer(token), params={"dry_run": True}
    )
    assert r.json()["applied"] is False
    got = await client.get(f"/documents/{doc_id}", headers=_bearer(token))
    assert got.json()["state"] == "pending"


async def test_list_filter_by_state(client, admin):
    _, token = admin
    keep = await _ingest(client, token, key="keep.md")
    gone = await _ingest(client, token, key="gone.md", content=b"remove me")
    await client.request("DELETE", f"/documents/{gone}", headers=_bearer(token))
    r = await client.get("/documents", headers=_bearer(token), params={"state": "soft_deleted"})
    ids = {d["id"] for d in r.json()}
    assert gone in ids
    assert keep not in ids


async def test_other_user_cannot_access(client, admin, db_session):
    _, token = admin
    doc_id = await _ingest(client, token, key="secret.md")
    other = await create_user(db_session, "other-doc@example.com")
    other_token, _ = await issue_token(db_session, other)
    r = await client.get(f"/documents/{doc_id}", headers=_bearer(other_token))
    assert r.status_code == 404
    listing = await client.get("/documents", headers=_bearer(other_token))
    assert listing.json() == []


async def test_unknown_document_is_404(client, admin):
    _, token = admin
    r = await client.get(f"/documents/{uuid.uuid4()}", headers=_bearer(token))
    assert r.status_code == 404
