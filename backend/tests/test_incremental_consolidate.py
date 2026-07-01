import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from odin.services import graph, resolution

_CLUSTER = {"helios": 0, "acme": 1}


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    async def embed(texts):
        out = []
        for t in texts:
            v = [0.0] * 1536
            v[_CLUSTER.get(t.split()[0].lower(), 100)] = 1.0
            out.append(v)
        return out

    monkeypatch.setattr(resolution.embedding, "embed_texts", embed)


@pytest.fixture(autouse=True)
def _confirm_merges(monkeypatch):
    async def complete(prompt, schema, system=None, model=None, max_tokens=None):
        if schema is resolution._SkepticVerdict:
            return schema(distinct=False, confidence=0.0, rationale="r")
        return schema(same=True, confidence=0.95, rationale="r")

    monkeypatch.setattr(resolution.llm, "complete_json", complete)


def _ex(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        entities=[SimpleNamespace(name=name, type="Org", confidence=0.9)],
        relations=[],
        objectives=[],
    )


async def _seed(worker_db, uid: uuid.UUID, name: str) -> None:
    async with worker_db() as s:
        doc = SimpleNamespace(id=uuid.uuid4(), owner_user_id=uid)
        await graph.upsert(s, doc, _ex(name), {}, "m")
        await s.commit()


async def test_incremental_only_consolidates_entities_created_after_watermark(
    worker_db, monkeypatch
):
    uid = uuid.uuid4()
    await _seed(worker_db, uid, "Helios Robotics")
    await _seed(worker_db, uid, "Helios")
    watermark = datetime.now(UTC)
    await _seed(worker_db, uid, "Acme Corporation")
    await _seed(worker_db, uid, "Acme")

    async with worker_db() as s:
        merged = await resolution.deep_consolidate(s, uid, since=watermark)
        await s.commit()

    assert merged == 1
    async with worker_db() as s:
        remaining = {e[0] for e in await graph.list_owner_entities(s, uid)}
    assert {"org:helios", "org:helios robotics"} <= remaining
    assert "org:acme" not in remaining


async def test_full_consolidates_all_entities(worker_db, monkeypatch):
    uid = uuid.uuid4()
    await _seed(worker_db, uid, "Helios Robotics")
    await _seed(worker_db, uid, "Helios")
    await _seed(worker_db, uid, "Acme Corporation")
    await _seed(worker_db, uid, "Acme")

    async with worker_db() as s:
        merged = await resolution.deep_consolidate(s, uid, since=None)
        await s.commit()

    assert merged == 2
    async with worker_db() as s:
        remaining = {e[0] for e in await graph.list_owner_entities(s, uid)}
    assert "org:helios" not in remaining
    assert "org:acme" not in remaining
    assert {"org:helios robotics", "org:acme corporation"} <= remaining
