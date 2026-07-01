import uuid

from odin.models import SleepRun, SleepState, User
from odin.services.auth import issue_token
from odin.services.users import create_user
from odin.worker import tasks
from sqlalchemy import select


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_consolidate_triggers_queued_run(client, admin):
    _, token = admin
    r = await client.post("/consolidate", headers=_bearer(token))
    assert r.status_code == 201
    body = r.json()
    assert body["type"] == "consolidate"
    assert body["state"] == "queued"
    assert body["id"]


async def test_same_type_second_trigger_conflicts(client, admin):
    _, token = admin
    assert (await client.post("/consolidate", headers=_bearer(token))).status_code == 201
    r2 = await client.post("/consolidate", headers=_bearer(token))
    assert r2.status_code == 409
    assert r2.json()["error"]["type"] == "conflict"


async def test_other_type_can_queue_alongside(client, admin):
    _, token = admin
    assert (await client.post("/consolidate", headers=_bearer(token))).status_code == 201
    r = await client.post("/dream", headers=_bearer(token))
    assert r.status_code == 201
    assert r.json()["state"] == "queued"


async def test_status_empty_when_no_runs(client, admin):
    _, token = admin
    r = await client.get("/consolidate/status", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json()["run"] is None


async def test_status_reports_queued(client, admin):
    _, token = admin
    await client.post("/dream", headers=_bearer(token))
    r = await client.get("/dream/status", headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["type"] == "dream"
    assert body["run"]["state"] == "queued"
    assert body["waiting_behind"] is None


async def test_status_waiting_behind_running(client, admin, db_session):
    _, token = admin
    await client.post("/consolidate", headers=_bearer(token))
    await client.post("/dream", headers=_bearer(token))
    running = await db_session.scalar(
        select(SleepRun).where(SleepRun.type == "consolidate")
    )
    running.state = SleepState.running
    await db_session.flush()
    r = await client.get("/dream/status", headers=_bearer(token))
    assert r.json()["waiting_behind"] == "consolidate"


async def test_single_flight_is_per_owner(client, admin, db_session):
    _, token = admin
    assert (await client.post("/consolidate", headers=_bearer(token))).status_code == 201
    other = await create_user(db_session, "other-sleep@example.com")
    other_token, _ = await issue_token(db_session, other)
    r = await client.post("/consolidate", headers=_bearer(other_token))
    assert r.status_code == 201


async def test_consolidate_task_records_merges(worker_db, monkeypatch):
    async def fake_consolidate(session, owner, *, keys=None):
        return 3

    monkeypatch.setattr(tasks.resolution, "deep_consolidate", fake_consolidate)

    async with worker_db() as s:
        user = User(email="sleep-consolidate@example.com")
        s.add(user)
        await s.flush()
        run = SleepRun(owner_user_id=user.id, type="consolidate", state=SleepState.queued)
        s.add(run)
        await s.commit()
        run_id = run.id

    await tasks.consolidate(run_id=str(run_id))

    async with worker_db() as s:
        got = await s.get(SleepRun, run_id)
        assert got.state == SleepState.succeeded
        assert got.stats == {"merges": 3}
        assert got.started_at is not None
        assert got.finished_at is not None


async def test_dream_task_is_plumbed_noop(worker_db):
    async with worker_db() as s:
        user = User(email="sleep-dream@example.com")
        s.add(user)
        await s.flush()
        run = SleepRun(owner_user_id=user.id, type="dream", state=SleepState.queued)
        s.add(run)
        await s.commit()
        run_id = run.id

    await tasks.dream(run_id=str(run_id))

    async with worker_db() as s:
        got = await s.get(SleepRun, run_id)
        assert got.state == SleepState.succeeded
        assert got.stats == {"note": "REM not yet implemented"}


async def test_task_no_op_when_run_missing(worker_db):
    await tasks.consolidate(run_id=str(uuid.uuid4()))
