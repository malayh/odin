import pytest
from odin.models import Document, Role
from odin.services import blobs
from odin.services.auth import issue_token
from odin.services.orgs import add_member, create_org, create_user
from sqlalchemy import select, text


@pytest.fixture(autouse=True)
def _fake_blob_put(monkeypatch):
    async def fake_put(data: bytes) -> str:
        return f"s3://odin/{blobs.content_hash(data)}"

    monkeypatch.setattr(blobs, "put", fake_put)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload(client, token, key, content, scope="personal"):
    return await client.post(
        "/ingest",
        headers=_bearer(token),
        data={"key": key, "scope": scope},
        files={"file": (key, content, "text/markdown")},
    )


async def test_ingest_returns_ids_then_dedups(client, admin):
    _, token = admin
    r = await _upload(client, token, "notes.md", b"hello world")
    assert r.status_code == 201
    body = r.json()
    assert body["document_id"]
    assert body["job_id"]
    assert body["deduped"] is False

    r2 = await _upload(client, token, "notes.md", b"hello world")
    assert r2.status_code == 201
    again = r2.json()
    assert again["deduped"] is True
    assert again["job_id"] is None
    assert again["document_id"] == body["document_id"]


async def test_changed_content_creates_superseding_version(client, admin, db_session):
    _, token = admin
    r1 = await _upload(client, token, "doc.md", b"v1 content")
    r2 = await _upload(client, token, "doc.md", b"v2 content changed")
    assert r2.json()["deduped"] is False
    assert r2.json()["document_id"] != r1.json()["document_id"]

    docs = (
        (await db_session.execute(select(Document).where(Document.key == "doc.md"))).scalars().all()
    )
    assert len(docs) == 2
    active = [d for d in docs if d.supersedes_id is None]
    superseded = [d for d in docs if d.supersedes_id is not None]
    assert len(active) == 1
    assert active[0].version == 2
    assert superseded[0].version == 1
    assert superseded[0].supersedes_id == active[0].id


async def test_ingest_defers_task_atomically(client, admin, db_session):
    _, token = admin
    r = await _upload(client, token, "deferme.md", b"defer this")
    job_id = r.json()["job_id"]
    deferred = await db_session.scalar(
        text("SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'ingest' "
             "AND args->>'job_id' = :jid"),
        {"jid": job_id},
    )
    assert deferred == 1


async def test_unsupported_format_is_422(client, admin):
    _, token = admin
    r = await _upload(client, token, "data.pdf", b"%PDF-1.4")
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "validation_error"


async def test_viewer_cannot_ingest_to_org(client, admin, db_session):
    admin_user, _ = admin
    org = await create_org(db_session, "IngestOrg", admin_user)
    viewer = await create_user(db_session, "viewer-ing@example.com")
    await add_member(db_session, org.id, viewer.id, Role.viewer)
    viewer_token, _ = await issue_token(db_session, viewer)

    r = await _upload(client, viewer_token, "x.md", b"data", scope=f"org:{org.id}")
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "forbidden"


async def test_non_member_cannot_ingest_to_org(client, admin, db_session):
    admin_user, _ = admin
    org = await create_org(db_session, "PrivateOrg", admin_user)
    stranger = await create_user(db_session, "stranger@example.com")
    token, _ = await issue_token(db_session, stranger)

    r = await _upload(client, token, "x.md", b"data", scope=f"org:{org.id}")
    assert r.status_code == 403
