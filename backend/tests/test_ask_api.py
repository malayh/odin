import re
import uuid

import pytest
from odin.models import Chunk, DocState, Document, Embedding, ScopeType
from odin.services import embedding, llm
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
        key=f"a-{uuid.uuid4()}.md",
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
    return doc


@pytest.fixture(autouse=True)
def _fake_providers(monkeypatch):
    async def fake_q(texts):
        return [_vec(0)]

    async def fake_llm(prompt, schema, system=None):
        if schema.__name__ == "_Ranking":
            return schema(rankings=[])
        ids = re.findall(r"\[doc ([0-9a-f-]+) \|", prompt)
        return schema(answer="grounded answer", confident=True, used_document_ids=ids)

    monkeypatch.setattr(embedding, "embed_texts", fake_q)
    monkeypatch.setattr(llm, "complete_json", fake_llm)


async def test_ask_returns_grounded_answer_with_citations(client, admin, db_session):
    admin_user, token = admin
    doc = await _seed_chunk(
        db_session, admin_user.id, ScopeType.personal, admin_user.id, "Mara founded Helios.", 0
    )

    r = await client.post("/ask", headers=_bearer(token), json={"question": "who founded Helios?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "grounded answer"
    assert body["confident"] is True
    assert len(body["citations"]) == 1
    c = body["citations"][0]
    assert c["document_id"] == str(doc.id)
    assert c["scope_type"] == "personal"


async def test_ask_refuses_when_no_corpus_match(client, admin, db_session):
    _, token = admin

    r = await client.post("/ask", headers=_bearer(token), json={"question": "anything?"})
    assert r.status_code == 200
    body = r.json()
    assert body["confident"] is False
    assert body["citations"] == []
    assert "knowledge base" in body["answer"]


async def test_ask_accepts_history_followup(client, admin, db_session):
    admin_user, token = admin
    await _seed_chunk(
        db_session, admin_user.id, ScopeType.personal, admin_user.id, "Mara founded Helios.", 0
    )

    r = await client.post(
        "/ask",
        headers=_bearer(token),
        json={
            "question": "when did she join?",
            "history": [
                {"role": "user", "content": "who founded Helios?"},
                {"role": "assistant", "content": "Mara Vance."},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["confident"] is True


async def test_ask_forbidden_for_unjoined_org(client, admin, db_session):
    _, token = admin
    owner = await create_user(db_session, "a-orgowner@example.com")
    org = await create_org(db_session, "AskOrg", owner)

    r = await client.post(
        "/ask", headers=_bearer(token), json={"question": "q", "scope": f"org:{org.id}"}
    )
    assert r.status_code == 403


async def test_ask_requires_auth(client):
    r = await client.post("/ask", json={"question": "q"})
    assert r.status_code == 401
