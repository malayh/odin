import uuid

import pytest
from odin.models import Chunk, DocState, Document, Embedding, ScopeType
from odin.services import embedding
from odin.services.orgs import create_org, create_user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _vec(i: int) -> list[float]:
    v = [0.0] * 1536
    v[i] = 1.0
    return v


async def _seed_chunk(session, owner_id, scope_type, scope_id, text, vec_idx):
    doc = Document(
        owner_user_id=owner_id,
        scope_type=scope_type,
        scope_id=scope_id,
        key=f"s-{uuid.uuid4()}.md",
        content_hash=uuid.uuid4().hex,
        version=1,
        state=DocState.indexed,
    )
    session.add(doc)
    await session.flush()
    c = Chunk(
        document_id=doc.id,
        ordinal=0,
        text=text,
        section_meta={"headings": ["H"]},
        char_start=0,
        char_end=len(text),
    )
    session.add(c)
    await session.flush()
    session.add(Embedding(chunk_id=c.id, vector=_vec(vec_idx)))
    await session.flush()
    return c


@pytest.fixture(autouse=True)
def _fake_query_embed(monkeypatch):
    async def fake_q(texts):
        return [_vec(0)]

    monkeypatch.setattr(embedding, "embed_texts", fake_q)


async def test_search_returns_ranked_hits(client, admin, db_session):
    admin_user, token = admin
    await _seed_chunk(db_session, admin_user.id, ScopeType.personal, admin_user.id, "alpha", 0)
    await _seed_chunk(db_session, admin_user.id, ScopeType.personal, admin_user.id, "beta", 1)

    r = await client.post("/search", headers=_bearer(token), json={"query": "q", "top_k": 5})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) == 2
    assert hits[0]["text"] == "alpha"
    assert hits[0]["score"] >= hits[1]["score"]
    h = hits[0]
    assert h["scope_type"] == "personal"
    expected = {"document_id", "chunk_id", "ordinal", "char_start", "char_end", "section_meta"}
    assert expected <= set(h)


async def test_search_excludes_other_users(client, admin, db_session):
    admin_user, token = admin
    await _seed_chunk(db_session, admin_user.id, ScopeType.personal, admin_user.id, "mine", 0)
    other = await create_user(db_session, "s-other@example.com")
    await _seed_chunk(db_session, other.id, ScopeType.personal, other.id, "theirs", 0)

    r = await client.post("/search", headers=_bearer(token), json={"query": "q"})
    texts = [h["text"] for h in r.json()["hits"]]
    assert "mine" in texts
    assert "theirs" not in texts


async def test_search_scope_narrows_to_personal(client, admin, db_session):
    admin_user, token = admin
    await _seed_chunk(db_session, admin_user.id, ScopeType.personal, admin_user.id, "p", 0)

    r = await client.post(
        "/search", headers=_bearer(token), json={"query": "q", "scope": "personal"}
    )
    assert r.status_code == 200
    assert [h["text"] for h in r.json()["hits"]] == ["p"]


async def test_search_forbidden_for_unjoined_org(client, admin, db_session):
    _, token = admin
    owner = await create_user(db_session, "s-orgowner@example.com")
    org = await create_org(db_session, "SearchOrg", owner)

    r = await client.post(
        "/search", headers=_bearer(token), json={"query": "q", "scope": f"org:{org.id}"}
    )
    assert r.status_code == 403


async def test_search_requires_auth(client):
    r = await client.post("/search", json={"query": "q"})
    assert r.status_code == 401
