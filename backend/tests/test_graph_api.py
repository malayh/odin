import uuid
from types import SimpleNamespace
from urllib.parse import quote

from odin.models import Document, User
from odin.services import graph


def _ent(name, type_):
    return SimpleNamespace(name=name, type=type_, confidence=0.9)


def _rel(subject, predicate, object_):
    return SimpleNamespace(subject=subject, predicate=predicate, object=object_, confidence=0.9)


def _ex(entities, relations):
    return SimpleNamespace(entities=entities, relations=relations)


async def _seed_doc(session, owner_id):
    doc = Document(
        owner_user_id=owner_id,
        key=f"{uuid.uuid4().hex}.md",
        content_hash=uuid.uuid4().hex,
    )
    session.add(doc)
    await session.flush()
    return doc


async def test_find_and_read_entity(client, admin, db_session):
    user, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    doc = await _seed_doc(db_session, user.id)
    await graph.upsert(
        db_session,
        doc,
        _ex(
            [_ent("Helios Robotics", "Org"), _ent("Atlas", "Project"), _ent("Mara", "Person")],
            [
                _rel("Helios Robotics", "builds", "Atlas"),
                _rel("Mara", "works_at", "Helios Robotics"),
            ],
        ),
        {},
        "m",
    )
    await db_session.flush()

    r = await client.get("/graph/entities", params={"q": "helios"})
    assert r.status_code == 200
    assert "org:helios robotics" in {e["key"] for e in r.json()}

    r = await client.get(f"/graph/entities/{quote('org:helios robotics', safe='')}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Helios Robotics"
    assert ("BUILDS", "project:atlas") in {
        (rel["predicate"], rel["object_key"]) for rel in body["relationships"]
    }

    r = await client.get(f"/graph/entities/{quote('person:nobody', safe='')}")
    assert r.status_code == 404


async def test_history_excludes_other_users_provenance(client, admin, db_session):
    user_a, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    user_b = User(email="iso-b@example.com")
    db_session.add(user_b)
    await db_session.flush()

    doc_a = await _seed_doc(db_session, user_a.id)
    doc_b = await _seed_doc(db_session, user_b.id)
    await graph.upsert(
        db_session,
        doc_a,
        _ex([_ent("Shared", "Org"), _ent("Anvil", "Product")], [_rel("Shared", "builds", "Anvil")]),
        {},
        "m",
    )
    await graph.upsert(
        db_session,
        doc_b,
        _ex(
            [_ent("Shared", "Org"), _ent("Secret", "Project")],
            [_rel("Shared", "builds", "Secret")],
        ),
        {},
        "m",
    )
    await db_session.flush()

    r = await client.get(f"/graph/entities/{quote('org:shared', safe='')}/history")
    assert r.status_code == 200
    text = r.text
    assert "product:anvil" in text
    assert "project:secret" not in text
    assert str(doc_b.id) not in text


async def test_entity_add_list_show(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/graph/entities", json={"type": "Person", "name": "Bob"})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["id"] == "person:bob"

    r = await client.get("/graph/entities", params={"type": "Person"})
    assert r.status_code == 200
    assert "person:bob" in {e["key"] for e in r.json()}

    r = await client.get(f"/graph/entities/{quote('person:bob', safe='')}")
    assert r.status_code == 200
    assert r.json()["name"] == "Bob"


async def test_edge_add_reflected_in_show(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    await client.post("/graph/entities", json={"type": "Person", "name": "Bob"})
    await client.post("/graph/entities", json={"type": "Org", "name": "Helios"})

    r = await client.post(
        "/graph/edges",
        json={"subject_key": "person:bob", "predicate": "works_at", "object_key": "org:helios"},
    )
    assert r.status_code == 200
    assert r.json()["applied"] is True

    r = await client.get(f"/graph/entities/{quote('person:bob', safe='')}")
    rels = {(x["predicate"], x["object_key"]) for x in r.json()["relationships"]}
    assert ("WORKS_AT", "org:helios") in rels


async def test_entity_rename_repoints_edges(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    await client.post("/graph/entities", json={"type": "Person", "name": "Bob"})
    await client.post("/graph/entities", json={"type": "Org", "name": "Helios"})
    await client.post(
        "/graph/edges",
        json={"subject_key": "person:bob", "predicate": "works_at", "object_key": "org:helios"},
    )

    r = await client.patch("/graph/entities/person:bob", json={"new_name": "Bobby"})
    assert r.status_code == 200
    assert r.json()["id"] == "person:bobby"

    r = await client.get(f"/graph/entities/{quote('person:bobby', safe='')}")
    rels = {(x["predicate"], x["object_key"]) for x in r.json()["relationships"]}
    assert ("WORKS_AT", "org:helios") in rels

    r = await client.get(f"/graph/entities/{quote('person:bob', safe='')}")
    assert r.status_code == 404


async def test_entity_drop(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    await client.post("/graph/entities", json={"type": "Person", "name": "Bob"})

    r = await client.delete("/graph/entities/person:bob")
    assert r.status_code == 200
    assert r.json()["applied"] is True

    r = await client.get(f"/graph/entities/{quote('person:bob', safe='')}")
    assert r.status_code == 404


async def test_dry_run_writes_nothing(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"
    await client.post("/graph/entities", json={"type": "Person", "name": "Bob"})

    r = await client.delete("/graph/entities/person:bob", params={"dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert "would drop" in body["summary"]

    r = await client.get(f"/graph/entities/{quote('person:bob', safe='')}")
    assert r.status_code == 200


async def test_objective_api_roundtrip(client, admin, db_session):
    _, token = admin
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/graph/objectives", json={"text": "ship L5"})
    assert r.status_code == 200
    oid = r.json()["id"]
    assert oid

    r = await client.get("/graph/objectives")
    assert r.status_code == 200
    assert [o["text"] for o in r.json()] == ["ship L5"]

    r = await client.delete(f"/graph/objectives/{oid}")
    assert r.status_code == 200
    assert r.json()["applied"] is True

    r = await client.get("/graph/objectives")
    assert r.json() == []
